"""Your Spotify library on the dashboard: playlists, saved albums, Liked Songs.

Reading an account needs that account's permission, unlike search. Spotify has
no password API and only sends a sign-in back to https or to the same machine,
so linking goes through the phone:

1. The Music page shows a QR code for /spotify/link on the Pi (backend/phone.py),
   which sends the phone on to Spotify's sign-in.
2. Spotify returns the phone to a small public page (deploy/spotify/callback/),
   which passes the result to the Pi at the address carried in `state`.
3. The Pi swaps it for tokens, proving with the PKCE verifier that only it could
   have asked. The public page sees neither the password nor anything usable.

The login is saved in ~/.config/baja-os/spotify-login.json (this user only), so
this happens once: it survives restarts and renews itself. It's dropped only
when Spotify says it's over, never for a failed connection; then the page shows
the code again. The library's last copy is kept in settings, for no signal.

Signing in needs nothing from Soloist: this reads the library, and what's
tapped plays through Soloist's own saved session.
"""

import base64
import hashlib
import hmac
import json
import math
import os
import secrets
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from PyQt6.QtCore import QObject, pyqtProperty, pyqtSignal, pyqtSlot

from backend import retry, safe_emit
from backend.spotifysearch import CREDENTIALS, TOKEN_MARGIN_S, TOKEN_URL, entry, read_credentials

AUTHORIZE_URL = "https://accounts.spotify.com/authorize"
REDIRECT_URI = "https://caleblykken.github.io/baja-spotify-link/"      # deploy/spotify/callback/
API = "https://api.spotify.com/v1/me/"
SCOPES = "playlist-read-private user-library-read"
LOGIN_FILE = Path("~/.config/baja-os/spotify-login.json").expanduser()
LIBRARY_SETTING = "spotifyLibrary"
LINK_LASTS_S = 600
PAGE_SIZE = 50                 # Spotify's most at a time; the first page of each is plenty to scroll
REFRESH_EVERY_S = 900


class SignedOut(Exception):
    """Spotify ended the login."""


def _post_form(fields):
    req = urllib.request.Request(TOKEN_URL, data=urllib.parse.urlencode(fields).encode(),
                                 headers={"Content-Type": "application/x-www-form-urlencoded"})

    def post():
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.load(r)
    return retry.call(post)


def _read_section(data, kind, key):
    """Entries from one page of a library list; `key` unwraps saved items."""
    items = data.get("items") if isinstance(data, dict) else None
    found = ((i.get(key) if key and isinstance(i, dict) else i) for i in items or [])
    return [e for e in (entry(kind, item) for item in found) if e]


class SpotifyAccount(QObject):
    changed = pyqtSignal()
    libraryChanged = pyqtSignal()
    _linked = pyqtSignal(bool, str)               # it worked, message
    _loaded = pyqtSignal(object, str, bool, int)  # library or None, message, signed out, sign-in it was read for

    def __init__(self, settings=None, credentials=CREDENTIALS, login_file=LOGIN_FILE, parent=None):
        super().__init__(parent)
        self._settings = settings
        self._credentials = credentials
        self._login_file = login_file
        self._refresh_token = self._read_login()
        self._access = ""
        self._access_until = 0.0
        self._lock = threading.Lock()
        self._login_lock = threading.Lock()   # guards the login against a worker finishing after a sign-out
        self._generation = 0                  # bumped whenever the login is dropped; workers carry the one they began with
        self._link = None              # {nonce, verifier, state, until}, while the QR code is up
        self._link_url = ""
        self._message = ""
        self._loading = False
        self._loaded_at = None
        self._library = {"playlists": [], "albums": [], "songs": []}
        self._load_saved_library()
        self._linked.connect(self._on_linked)
        self._loaded.connect(self._on_loaded)

    def start(self):
        if self.linked:
            self.refresh()

    # ---- the saved login ----------------------------------------------------
    def _read_login(self):
        try:
            return str(json.loads(self._login_file.read_text()).get("refresh_token", ""))
        except (OSError, ValueError, AttributeError):
            return ""

    def _save_login(self, token):
        """Written beside the old one and renamed over it, so a power cut
        leaves one login or the other, never half a file."""
        self._login_file.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self._login_file.parent, prefix=".spotify-login-")    # made 0600
        try:
            with os.fdopen(fd, "w") as f:
                json.dump({"refresh_token": token}, f)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, self._login_file)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
        self._refresh_token = token

    def _drop_login(self):
        with self._login_lock:
            self._generation += 1                 # whatever is still in flight belongs to the login that's gone
            self._refresh_token, self._access = "", ""
            try:
                self._login_file.unlink()
            except OSError:
                pass

    def _load_saved_library(self):
        if not self._settings or not self._refresh_token:
            return
        try:
            saved = json.loads(str(self._settings.get(LIBRARY_SETTING, "{}")))
        except ValueError:
            return
        if isinstance(saved, dict):
            for key in self._library:
                if isinstance(saved.get(key), list):
                    self._library[key] = saved[key]

    # ---- linking: from the UI thread ----------------------------------------
    @pyqtSlot(str, int)
    def startLink(self, ip, port):
        """Get ready for a phone, and show the code for this Pi's address."""
        if not ip or not self.available:
            return
        nonce = secrets.token_urlsafe(16)
        self._link = {"nonce": nonce, "verifier": secrets.token_urlsafe(64),
                      "state": f"{secrets.token_urlsafe(16)}~{ip}~{port}",
                      "until": time.monotonic() + LINK_LASTS_S}
        self._link_url = f"http://{ip}:{port}/spotify/link?s={nonce}"
        self._message = ""
        self.changed.emit()

    @pyqtSlot()
    def cancelLink(self):
        if self._link or self._link_url:
            self._link, self._link_url = None, ""
            self.changed.emit()

    @pyqtSlot()
    def signOut(self):
        self._drop_login()
        self._library = {"playlists": [], "albums": [], "songs": []}
        if self._settings:
            self._settings.set(LIBRARY_SETTING, "{}")
        self.changed.emit()
        self.libraryChanged.emit()

    # ---- linking: from the phone server's threads ---------------------------
    def authorize_url(self, nonce):
        """Where to send the phone, or '' if this isn't the code on screen."""
        link = self._link
        if not (link and time.monotonic() < link["until"]
                and hmac.compare_digest(nonce.encode(), link["nonce"].encode())):
            return ""
        digest = hashlib.sha256(link["verifier"].encode()).digest()
        challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
        client, _ = read_credentials(self._credentials)
        return AUTHORIZE_URL + "?" + urllib.parse.urlencode({
            "client_id": client, "response_type": "code", "redirect_uri": REDIRECT_URI,
            "code_challenge_method": "S256", "code_challenge": challenge,
            "state": link["state"], "scope": SCOPES})

    def callback(self, code, state, error):
        """The phone is back from Spotify: (accepted, what to tell it)."""
        link = self._link
        if not (link and hmac.compare_digest(state.encode(), link["state"].encode())):
            return False, "That link has expired. Show the code on the dashboard again."
        self._link = None                        # one use
        generation = self._generation
        if error or not code:
            safe_emit(self, "_linked", False, "Spotify wasn't linked")
            return False, "Spotify wasn't linked."

        def work():
            try:
                client, _ = read_credentials(self._credentials)
                tokens = _post_form({"grant_type": "authorization_code", "code": code,
                                     "redirect_uri": REDIRECT_URI, "client_id": client,
                                     "code_verifier": link["verifier"]})
                with self._login_lock:
                    if generation != self._generation:        # signed out while Spotify was answering
                        raise SignedOut()
                    self._save_login(str(tokens["refresh_token"]))
                    self._keep_access(tokens)
                safe_emit(self, "_linked", True, "")
            except SignedOut:
                safe_emit(self, "_linked", False, "")
            except Exception as e:               # always answer, or the link screen waits forever
                print(f"Spotify account: linking failed ({type(e).__name__})", flush=True)
                safe_emit(self, "_linked", False, "Couldn't finish linking Spotify")
        threading.Thread(target=work, daemon=True).start()
        return True, "Spotify is linked. You can go back to the truck."

    def _on_linked(self, ok, message):
        self._link_url, self._message = "", message
        self.changed.emit()
        if ok:
            self.refresh()

    # ---- reading the library ------------------------------------------------
    def _keep_access(self, tokens):
        if not isinstance(tokens, dict):
            raise ValueError("token reply isn't an object")
        self._access = str(tokens["access_token"])
        try:
            lifetime = float(tokens.get("expires_in", 3600))
        except (TypeError, ValueError):
            lifetime = 3600.0
        if not math.isfinite(lifetime):
            lifetime = 3600.0
        self._access_until = time.monotonic() + lifetime - TOKEN_MARGIN_S

    def _valid_access(self):
        with self._lock:
            if self._access and time.monotonic() < self._access_until:
                return self._access
            generation, token = self._generation, self._refresh_token
            if not token:
                raise SignedOut()                 # nothing to renew with
            client, _ = read_credentials(self._credentials)
            try:
                tokens = _post_form({"grant_type": "refresh_token", "client_id": client,
                                     "refresh_token": token})
            except urllib.error.HTTPError as e:
                if e.code == 400 and b"invalid_grant" in e.read():
                    raise SignedOut() from None
                raise
            with self._login_lock:
                if generation != self._generation:    # signed out during the request: don't bring it back
                    raise SignedOut()
                self._keep_access(tokens)
                newer = tokens.get("refresh_token")   # Spotify may or may not send a new one
                if newer and newer != self._refresh_token:
                    self._save_login(str(newer))
                return self._access

    def _get(self, path):
        def get():
            req = urllib.request.Request(f"{API}{path}?limit={PAGE_SIZE}",
                                         headers={"Authorization": "Bearer " + self._valid_access()})
            with urllib.request.urlopen(req, timeout=10) as r:
                return json.load(r)
        try:
            return retry.call(get)
        except urllib.error.HTTPError as e:
            if e.code != 401:
                raise
            self._access = ""                    # turned down early: one try with a new token
            return retry.call(get)

    def _section(self, path, kind, key, old):
        """One list; if Spotify refuses just this one, keep what we had."""
        try:
            return _read_section(self._get(path), kind, key)
        except urllib.error.HTTPError as e:
            if e.code in (401, 429) or e.code >= 500:
                raise
            print(f"Spotify account: {path} refused ({e.code})", flush=True)
            return old

    @pyqtSlot()
    def refresh(self):
        if self._loading or not self.linked:
            return
        self._loading, self._message = True, ""
        self.changed.emit()
        old = self._library
        generation = self._generation

        def work():
            library, message, signed_out = None, "", False
            try:
                library = {"playlists": self._section("playlists", "playlist", None, old["playlists"]),
                           "albums": self._section("albums", "album", "album", old["albums"]),
                           "songs": self._section("tracks", "track", "track", old["songs"])}
            except SignedOut:
                signed_out, message = True, "Spotify ended the sign-in: scan the code to link it again"
            except (OSError, ValueError, KeyError) as e:
                print(f"Spotify account: couldn't read the library ({type(e).__name__})", flush=True)
                message = "Can't reach Spotify right now"
            finally:
                safe_emit(self, "_loaded", library, message, signed_out, generation)
        threading.Thread(target=work, daemon=True).start()

    def _on_loaded(self, library, message, signed_out, generation):
        self._loading = False
        if generation != self._generation:        # signed out (or re-linked) since this began: its answer is stale
            self.changed.emit()
            return
        self._message = message
        if signed_out:
            self._drop_login()
        if library is not None:
            self._loaded_at = time.monotonic()
            if library != self._library:
                self._library = library
                if self._settings:
                    self._settings.set(LIBRARY_SETTING, json.dumps(library))
                self.libraryChanged.emit()
        self.changed.emit()

    def set_online(self, online):
        """Catch up when the connection comes (from backend/network.py)."""
        due = self._loaded_at is None or time.monotonic() - self._loaded_at > REFRESH_EVERY_S
        if online and due:
            self.refresh()

    # ---- what QML sees ------------------------------------------------------
    @pyqtProperty(bool, notify=changed)
    def available(self):
        """The Spotify app's ID is on this Pi."""
        return bool(read_credentials(self._credentials)[0])

    @pyqtProperty(bool, notify=changed)
    def linked(self):
        return bool(self._refresh_token)

    @pyqtProperty(str, notify=changed)
    def linkUrl(self):
        """What the QR code opens, while one is up, else ''."""
        return self._link_url

    @pyqtProperty(bool, notify=changed)
    def loading(self):
        return self._loading

    @pyqtProperty(str, notify=changed)
    def message(self):
        return self._message

    @pyqtProperty("QVariantList", notify=libraryChanged)
    def playlists(self):
        return self._library["playlists"]

    @pyqtProperty("QVariantList", notify=libraryChanged)
    def albums(self):
        return self._library["albums"]

    @pyqtProperty("QVariantList", notify=libraryChanged)
    def songs(self):
        return self._library["songs"]
