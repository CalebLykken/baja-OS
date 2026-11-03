"""Searching Spotify from the dashboard, through the Spotify Web API.

Soloist can play anything but can't search, so this finds the songs, albums
and playlists and backend/spotify.py plays what's tapped. Searching reads no
one's account, so it uses an app token (the client-credentials flow) and needs
no sign-in; deploy/spotify/set-spotify-search.sh stores the app's ID and
secret. Without them `available` is False and the page says what to run.

It searches when Search is pressed rather than on every key, which spares the
hotspot's data and the app's rate limit. Requests run on a worker thread; only
the newest search's answer is shown.
"""

import base64
import json
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from PyQt6.QtCore import QObject, pyqtProperty, pyqtSignal, pyqtSlot

from backend import retry, safe_emit

TOKEN_URL = "https://accounts.spotify.com/api/token"
SEARCH_URL = "https://api.spotify.com/v1/search"
CREDENTIALS = Path("~/.config/baja-os/spotify-search.env").expanduser()
KINDS = ("track", "album", "playlist")   # Soloist can't start an artist, so they're left out
LIMIT = 6                                # of each kind; development-mode apps get 10 at most
MARKET = "US"                            # an app token has no account to take a country from
ART_WIDTH = 64                           # the smallest cover that suits a row, to spare the data
TOKEN_MARGIN_S = 60                      # renew this long before it runs out


def read_credentials(path=CREDENTIALS):
    """(client id, secret) from the file, or ('', '') if it isn't complete."""
    try:
        lines = path.read_text().splitlines()
    except (OSError, UnicodeDecodeError):
        return "", ""
    values = dict(l.split("=", 1) for l in lines if "=" in l)
    client, secret = (values.get(k, "").strip() for k in ("SPOTIFY_CLIENT_ID", "SPOTIFY_CLIENT_SECRET"))
    return (client, secret) if client and secret else ("", "")


def _art(images):
    """The smallest cover at least ART_WIDTH wide, else the last one, or ''."""
    shown = [i for i in images or [] if isinstance(i, dict) and i.get("url")]
    big_enough = [i for i in shown if (i.get("width") or 0) >= ART_WIDTH]
    if big_enough:
        return min(big_enough, key=lambda i: i["width"])["url"]
    return shown[-1]["url"] if shown else ""


def _artists(item):
    return ", ".join(a.get("name", "") for a in item.get("artists") or [] if isinstance(a, dict))


def entry(kind, item):
    """{uri, kind, title, subtitle, art} for a Web API item, or None if it
    isn't a whole one (Spotify leaves nulls in its lists)."""
    if not (isinstance(item, dict) and item.get("uri") and item.get("name")):
        return None
    if kind == "track":
        subtitle, images = _artists(item), (item.get("album") or {}).get("images")
    elif kind == "album":
        subtitle, images = "Album, " + _artists(item), item.get("images")
    else:
        owner = (item.get("owner") or {}).get("display_name")
        subtitle, images = f"Playlist, {owner}" if owner else "Playlist", item.get("images")
    return {"uri": item["uri"], "kind": kind, "title": item["name"],
            "subtitle": subtitle, "art": _art(images)}


def parse_results(data):
    """The entries found: songs, then albums, then playlists."""
    out = []
    for kind in KINDS:
        section = data.get(kind + "s") if isinstance(data, dict) else None
        found = (entry(kind, item) for item in (section or {}).get("items") or [])
        out += [e for e in found if e]
    return out


class SpotifySearch(QObject):
    changed = pyqtSignal()
    _answered = pyqtSignal(int, object, str)      # which search, results, message

    def __init__(self, credentials=CREDENTIALS, parent=None):
        super().__init__(parent)
        self._credentials = credentials
        self._results = []
        self._searching = False
        self._message = ""
        self._newest = 0
        self._token = ""
        self._token_until = 0.0
        self._token_lock = threading.Lock()
        self._answered.connect(self._on_answered)

    # ---- talking to Spotify -------------------------------------------------
    def _new_token(self, client, secret):
        pair = base64.b64encode(f"{client}:{secret}".encode()).decode()
        req = urllib.request.Request(TOKEN_URL, data=b"grant_type=client_credentials",
                                     headers={"Authorization": "Basic " + pair,
                                              "Content-Type": "application/x-www-form-urlencoded"})

        def get():
            with urllib.request.urlopen(req, timeout=10) as r:
                return json.load(r)
        answer = retry.call(get)
        self._token = str(answer["access_token"])
        self._token_until = time.monotonic() + float(answer.get("expires_in", 3600)) - TOKEN_MARGIN_S

    def _valid_token(self, client, secret):
        with self._token_lock:
            if not self._token or time.monotonic() >= self._token_until:
                self._new_token(client, secret)
            return self._token

    def _get(self, text, token):
        query = urllib.parse.urlencode({"q": text, "type": ",".join(KINDS), "limit": LIMIT, "market": MARKET})
        req = urllib.request.Request(f"{SEARCH_URL}?{query}", headers={"Authorization": "Bearer " + token})

        def get():
            with urllib.request.urlopen(req, timeout=10) as r:
                return json.load(r)
        return retry.call(get)

    def _find(self, text):
        client, secret = read_credentials(self._credentials)
        try:
            return self._get(text, self._valid_token(client, secret))
        except urllib.error.HTTPError as e:
            if e.code != 401:
                raise
            self._token = ""                     # turned down early: one try with a new token
            return self._get(text, self._valid_token(client, secret))

    # ---- what QML sees ------------------------------------------------------
    @pyqtSlot(str)
    def search(self, text):
        text = text.strip()
        if not text or not self.available:
            return
        self._newest += 1
        which = self._newest
        self._searching, self._message = True, ""
        self.changed.emit()

        def work():
            results, message = [], ""
            try:
                results = parse_results(self._find(text))
                if not results:
                    message = f"Nothing on Spotify for {text}"
            except urllib.error.HTTPError as e:
                print(f"Spotify search: HTTP {e.code}", flush=True)
                message = ("Spotify search is busy, try again in a minute" if e.code == 429
                           else "Spotify turned the search down: check its app key on the Pi")
            except (OSError, ValueError, KeyError) as e:
                print(f"Spotify search: {type(e).__name__}", flush=True)
                message = "Can't reach Spotify. Is the phone's hotspot connected?"
            finally:
                safe_emit(self, "_answered", which, results, message)
        threading.Thread(target=work, daemon=True).start()

    def _on_answered(self, which, results, message):
        if which == self._newest:
            self._results, self._searching, self._message = results, False, message
            self.changed.emit()

    @pyqtSlot()
    def clear(self):
        self._newest += 1                        # an answer on its way is no longer wanted
        self._results, self._searching, self._message = [], False, ""
        self.changed.emit()

    @pyqtProperty(bool, notify=changed)
    def available(self):
        """The app's ID and secret are on this Pi."""
        return all(read_credentials(self._credentials))

    @pyqtProperty("QVariantList", notify=changed)
    def results(self):
        return self._results

    @pyqtProperty(bool, notify=changed)
    def searching(self):
        return self._searching

    @pyqtProperty(str, notify=changed)
    def message(self):
        return self._message
