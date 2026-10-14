"""Send a destination from the phone to the dashboard.

Two ways in, both over Wi-Fi (the phone's hotspot in the truck, or home
Wi-Fi), both needing the token in ~/.config/baja-os/send-token:

- An iPhone Share-sheet Shortcut ("Send to Baja") POSTs whatever Maps
  shared to /api/v1/destination with "Authorization: Bearer <token>".
- Scanning the QR code in Settings opens /send on the phone: a page to
  paste a link or type a place, which also shows how to set up the
  Shortcut.

Whatever arrives (an Apple Maps or Google Maps link, short links included,
coordinates, an address, a place name) is turned into a place with a
position, checked against the offline map's area, and handed to the Maps
page, which shows it with a Go key. Nothing starts driving by itself.
"""

import hmac
import html
import ipaddress
import json
import os
import re
import secrets
import socket
import sqlite3
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from PyQt6.QtCore import QObject, QUrl, pyqtProperty, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QColor, QImage, QPainter

from backend import places
from backend.vendor.qrcodegen import QrCode

PORT = 8780
TOKEN_FILE = Path("~/.config/baja-os/send-token").expanduser()
HOTSPOT_ADDRESS = "172.20.10.14"       # the fixed extra address on an iPhone hotspot (wifi.py)
MAX_BODY = 16 * 1024
ALLOWED_NETS = [ipaddress.ip_network(n) for n in
                ("127.0.0.0/8", "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")]
SHORT_LINK_HOSTS = ("maps.apple", "maps.app.goo.gl", "goo.gl")
URL_RE = re.compile(r"(?:https?://|geo:)[^\s<>\"']+")
LATLON_RE = re.compile(r"(-?\d{1,2}\.\d{3,})\s*,\s*(-?\d{1,3}\.\d{3,})")


def load_token():
    """The shared secret, made on first use (readable by this user only)."""
    try:
        token = TOKEN_FILE.read_text().strip()
        if len(token) >= 32:
            return token
    except OSError:
        pass
    TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    token = secrets.token_urlsafe(32)
    fd = os.open(TOKEN_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(token + "\n")
    return token


# ---- turning what was shared into a place ----------------------------------------------

def _latlon(value):
    m = re.fullmatch(r"\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*", value or "")
    if m:
        lat, lon = float(m[1]), float(m[2])
        if -90 <= lat <= 90 and -180 <= lon <= 180:
            return lat, lon
    return None


def expand_short_link(url):
    """One request, no redirects: the Location header of a maps short link
    has the place in it. Only for known map hosts."""
    host = urllib.parse.urlsplit(url).hostname or ""
    if not any(host == h or host.endswith("." + h) for h in SHORT_LINK_HOSTS):
        return url

    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs):
            return None

    opener = urllib.request.build_opener(NoRedirect)
    req = urllib.request.Request(url, headers={"User-Agent": "BajaOS/1"})
    try:
        opener.open(req, timeout=5)
    except urllib.error.HTTPError as e:
        location = e.headers.get("Location")
        if location:
            parts = urllib.parse.urlsplit(location)
            if parts.hostname and parts.hostname.startswith("consent.google."):
                cont = urllib.parse.parse_qs(parts.query).get("continue")
                if cont:
                    return cont[0]
            return location
    except (OSError, ValueError):
        pass
    return url


def parse_map_url(url):
    """(lat, lon or None, label) from an Apple Maps, Google Maps or geo: link."""
    if url.startswith("geo:"):
        body = url[4:]
        coords, _, query = body.partition("?")
        q = urllib.parse.parse_qs(query).get("q", [""])[0]
        ll = _latlon(coords.split(";")[0])
        label = re.sub(r"^[-\d.]+,[-\d.]+\s*", "", q).strip("() ")
        return ll, label
    parts = urllib.parse.urlsplit(url)
    host = parts.hostname or ""
    qs = {k: v[0] for k, v in urllib.parse.parse_qs(parts.query).items()}
    path = urllib.parse.unquote_plus(parts.path)
    ll, label = None, ""
    if "apple" in host:
        for key in ("coordinate", "ll", "destination", "daddr", "center", "sll"):
            ll = ll or _latlon(qs.get(key))
        name, address = qs.get("name", ""), qs.get("address", "")
        label = f"{name}, {address}" if name and address else (name or address or qs.get("q") or "")
        if not label and not _latlon(qs.get("destination", "")):
            label = qs.get("destination") or qs.get("daddr") or ""
    elif "google" in host or "goo.gl" in host:
        m = re.search(r"!3d(-?\d+\.\d+)!4d(-?\d+\.\d+)", url)
        if m:
            ll = (float(m[1]), float(m[2]))
        for key in ("q", "query", "destination", "daddr"):
            ll = ll or _latlon(qs.get(key))
        if not ll:
            m = re.search(r"@(-?\d+\.\d+),(-?\d+\.\d+)", url)
            if m:
                ll = (float(m[1]), float(m[2]))
        m = re.search(r"/maps/place/([^/]+)", path)
        if m and not _latlon(m[1]):
            label = m[1]
        elif "/maps/dir/" in path:
            stops = [s for s in path.split("/maps/dir/", 1)[1].split("/") if s and not s.startswith("@") and not s.startswith("data=")]
            if stops and not _latlon(stops[-1]):
                label = stops[-1]
        for key in ("q", "query", "destination"):
            if not label and qs.get(key) and not _latlon(qs.get(key)):
                label = qs[key]
    return ll, label.strip()


def resolve(payload, maps_dir):
    """A place dict {name, label, lon, lat} from what the phone sent, or
    raise ValueError with a message the phone can show."""
    text = str(payload.get("text") or "")
    urls = payload.get("urls") or []
    if isinstance(urls, str):
        urls = urls.split()
    urls = [u for u in list(urls) + URL_RE.findall(text) if u]
    if any("/guides/" in u or "/lists/" in u for u in urls):
        raise ValueError("That's a list, not a place")

    ll, label = None, ""
    for url in dict.fromkeys(urls):                  # each once, in order
        u_ll, u_label = parse_map_url(expand_short_link(url))
        ll, label = ll or u_ll, label or u_label
    if not ll and payload.get("lat") not in (None, "") and payload.get("lon") not in (None, ""):
        try:
            ll = (float(payload["lat"]), float(payload["lon"]))
        except (TypeError, ValueError):
            pass
    label = label or str(payload.get("name") or "")
    if not ll:
        m = LATLON_RE.search(URL_RE.sub(" ", text))
        if m:
            ll = (float(m[1]), float(m[2]))

    region = {}
    try:
        region = json.loads((Path(maps_dir) / "region.json").read_text())
    except (OSError, ValueError):
        pass

    if not ll:
        # No position in it: look the words up in the offline map.
        lines = [l.strip() for l in ([label] + URL_RE.sub(" ", text).splitlines()) if l and l.strip()]
        for line in lines:
            hit = _search_offline(line, maps_dir)
            if hit:
                return hit
        raise ValueError("Couldn't find that in the offline map")

    lat, lon = ll
    w, s, e, n = region.get("bbox", (-180, -90, 180, 90))
    if not (w <= lon <= e and s <= lat <= n):
        raise ValueError("That's outside the offline map (" + region.get("region", "this area") + ")")
    name = label.split(",")[0].strip()
    detail = label[len(name):].strip(" ,") if name and label.startswith(name) else ""
    if not name:
        name = _nearest_name(lon, lat, maps_dir) or "Dropped pin"
    return {"name": name, "label": detail or "Sent from your phone", "lon": lon, "lat": lat}


def _nearest_name(lon, lat, maps_dir, within_m=60):
    """The name of the closest mapped place to a bare coordinate, if close."""
    try:
        db = sqlite3.connect(f"file:{Path(maps_dir) / places.INDEX_NAME}?mode=ro", uri=True)
        k = places.math.cos(places.math.radians(lat)) ** 2
        row = db.execute("SELECT name, lon, lat FROM places WHERE kind != 'street'"
                         " ORDER BY (lon - ?) * (lon - ?) * ? + (lat - ?) * (lat - ?) LIMIT 1",
                         (lon, lon, k, lat, lat)).fetchone()
        db.close()
    except sqlite3.Error:
        return ""
    if not row:
        return ""
    dx = (row[1] - lon) * 111320 * places.math.cos(places.math.radians(lat))
    dy = (row[2] - lat) * 110540
    return row[0] if (dx * dx + dy * dy) ** 0.5 <= within_m else ""


def _search_offline(text, maps_dir):
    maps_dir = Path(maps_dir)
    try:
        if places.looks_like_address(text) and (maps_dir / places.ADDRESS_INDEX).is_file():
            db = sqlite3.connect(f"file:{maps_dir / places.ADDRESS_INDEX}?mode=ro", uri=True)
            # Drop the city, state and ZIP that addresses usually come with.
            street = re.split(r",", text)[0]
            rows = places.search_addresses(db, street)
            db.close()
            if rows:
                r = rows[0]
                return {"name": r["name"], "label": r["area"] or "Address", "lon": r["lon"], "lat": r["lat"]}
        db = sqlite3.connect(f"file:{maps_dir / places.INDEX_NAME}?mode=ro", uri=True)
        rows = places.search(db, text, limit=1)
        db.close()
    except sqlite3.Error:
        return None
    if rows:
        r = rows[0]
        return {"name": r["name"], "label": r["kind"].replace("_", " ").capitalize(), "lon": r["lon"], "lat": r["lat"]}
    return None


# ---- the web side -----------------------------------------------------------------------

PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Send to Baja</title>
<style>
  :root { color-scheme: dark; }
  body { margin: 0; padding: 20px 16px 40px; background: #14160f; color: #e9dfc4;
         font: 17px/1.45 -apple-system, system-ui, sans-serif; }
  h1 { font-size: 26px; margin: 0 0 6px; }
  h2 { font-size: 19px; margin: 32px 0 8px; }
  p, li { color: #c9c0a6; }
  textarea { width: 100%; box-sizing: border-box; min-height: 110px; padding: 12px; font: inherit;
             color: #e9dfc4; background: #1e2118; border: 2px solid #4a4a35; border-radius: 6px; }
  button { margin-top: 12px; width: 100%; padding: 14px; font: 600 18px system-ui; border: 0;
           border-radius: 6px; background: #ff7a1a; color: #14160f; }
  button.quiet { background: #2c3123; color: #e9dfc4; border: 2px solid #4a4a35; }
  code { display: block; padding: 10px; background: #1e2118; border-radius: 6px; word-break: break-all; color: #e9dfc4; }
  #result { margin-top: 12px; font-weight: 600; min-height: 1.4em; }
  ol { padding-left: 22px; }
</style></head><body>
<h1>Send to Baja</h1>
<p>Paste a link from Apple Maps or Google Maps, an address, or a place name.</p>
<textarea id="text" placeholder="https://maps.apple/p/...   or   400 Broad St, Seattle"></textarea>
<button id="send">Send to the dashboard</button>
<div id="result"></div>

<h2>Faster: a Share-sheet Shortcut</h2>
<p>Then you can tap Share, then Send to Baja, from Apple Maps or Google Maps.</p>
<ol>
<li>Open Shortcuts, tap +, name it <b>Send to Baja</b>. In its details, turn on <b>Show in Share Sheet</b> and let it receive URLs, Text, Maps links, Locations and Safari webpages.</li>
<li>Add <b>Get URLs from Input</b> (input: Shortcut Input).</li>
<li>Add <b>Text</b> and put <b>Shortcut Input</b> in it.</li>
<li>Add <b>Get Contents of URL</b> with the address below. Show more: Method <b>POST</b>; add header <b>Authorization</b> = <b>Bearer</b>, a space, then the token below; Request Body <b>JSON</b> with fields <b>text</b> = the Text result and <b>urls</b> = the URLs result.</li>
<li>Add <b>Get Dictionary Value</b> for key <b>message</b>, then <b>Show Notification</b>.</li>
<li>The first time, tap <b>Always Allow</b> (and <b>Allow</b> if it asks about the local network).</li>
</ol>
<p>Address:</p><code id="api">{{api}}</code>
<button class="quiet" data-copy="api">Copy address</button>
<p>Token:</p><code id="token">{{token}}</code>
<button class="quiet" data-copy="token">Copy token</button>
<script>
document.querySelectorAll("[data-copy]").forEach(b => b.onclick = async () => {
  await navigator.clipboard.writeText(document.getElementById(b.dataset.copy).textContent);
  b.textContent = "Copied";
});
document.getElementById("send").onclick = async () => {
  const out = document.getElementById("result");
  out.textContent = "Sending...";
  try {
    const r = await fetch("/api/v1/destination", { method: "POST", credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text: document.getElementById("text").value, source: "page" }) });
    out.textContent = (await r.json()).message;
  } catch (e) { out.textContent = "Couldn't reach the dashboard"; }
};
</script>
</body></html>
"""


class _Handler(BaseHTTPRequestHandler):
    server_version = "BajaOS/1"

    def log_message(self, *args):
        pass

    def _allowed_client(self):
        try:
            ip = ipaddress.ip_address(self.client_address[0])
        except ValueError:
            return False
        return any(ip in net for net in ALLOWED_NETS)

    def _authorised(self):
        svc = self.server.service
        if svc.blocked(self.client_address[0]):
            return False
        token = ""
        auth = self.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            token = auth[7:].strip()
        for part in self.headers.get("Cookie", "").split(";"):
            k, _, v = part.strip().partition("=")
            if k == "baja_send" and not token:
                token = v
        ok = bool(token) and hmac.compare_digest(token.encode(), svc.token.encode())
        if not ok:
            svc.failed(self.client_address[0])
        return ok

    def _send(self, code, body, ctype="application/json", extra=()):
        data = body.encode() if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        for k, v in extra:
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)

    def _json(self, code, ok, message):
        self._send(code, json.dumps({"ok": ok, "message": message}))

    def do_GET(self):
        if not self._allowed_client():
            return self._send(403, "forbidden", "text/plain")
        parts = urllib.parse.urlsplit(self.path)
        if parts.path != "/send":
            return self._send(404, "not found", "text/plain")
        key = urllib.parse.parse_qs(parts.query).get("k", [""])[0]
        svc = self.server.service
        if key:
            # From the QR code: swap the key in the link for a cookie.
            if not svc.blocked(self.client_address[0]) and hmac.compare_digest(key.encode(), svc.token.encode()):
                cookie = f"baja_send={key}; HttpOnly; SameSite=Strict; Path=/; Max-Age=31536000"
                return self._send(303, "", "text/plain", [("Location", "/send"), ("Set-Cookie", cookie)])
            svc.failed(self.client_address[0])
            return self._send(403, "That link has expired; scan the code on the dashboard again.", "text/plain")
        if not self._authorised():
            return self._send(403, "Scan the code in the dashboard's Settings > Map to open this page.", "text/plain")
        host = self.headers.get("Host", f"{svc.address}:{PORT}")
        page = (PAGE.replace("{{api}}", html.escape(f"http://{host}/api/v1/destination"))
                    .replace("{{token}}", html.escape(svc.token)))
        self._send(200, page, "text/html; charset=utf-8")

    def do_POST(self):
        if not self._allowed_client():
            return self._json(403, False, "Not from this network")
        if urllib.parse.urlsplit(self.path).path != "/api/v1/destination":
            return self._json(404, False, "Not found")
        if not self._authorised():
            return self._json(401, False, "Wrong token: check the Shortcut's Authorization header")
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0
        if length <= 0 or length > MAX_BODY:
            return self._json(413, False, "Too much (or nothing) was sent")
        try:
            payload = json.loads(self.rfile.read(length) or b"{}")
            if not isinstance(payload, dict):
                raise ValueError("expected an object")
        except ValueError:
            return self._json(400, False, "That wasn't JSON")
        try:
            place = resolve(payload, self.server.service.maps_dir)
        except ValueError as e:
            return self._json(422, False, str(e))
        self.server.service.deliver(place)
        return self._json(200, True, f"Sent to Baja: {place['name']}")


class PhoneSend(QObject):
    """The receiver, plus what Settings shows to set the phone up."""

    received = pyqtSignal("QVariantMap")
    changed = pyqtSignal()

    def __init__(self, maps_dir, parent=None):
        super().__init__(parent)
        self.maps_dir = Path(maps_dir)
        self.token = load_token()
        self._failures = {}           # ip -> [count, first failure time]
        self._server = None
        self._qr_dir = Path(os.environ.get("XDG_RUNTIME_DIR") or "/tmp")
        self._qr_for = ""
        self._qr_path = None
        self.address = ""
        self.received.connect(lambda _p: None)

    def start(self):
        try:
            self._server = ThreadingHTTPServer(("0.0.0.0", PORT), _Handler)
        except OSError as e:
            print(f"Send to Baja: can't listen on port {PORT} ({e})")
            return
        self._server.daemon_threads = True
        self._server.service = self
        threading.Thread(target=self._server.serve_forever, name="phone-send", daemon=True).start()

    # ---- used by the request handler (worker threads) -------------------------------------
    def blocked(self, ip):
        count, first = self._failures.get(ip, (0, 0))
        if time.monotonic() - first > 600:
            self._failures.pop(ip, None)
            return False
        return count >= 10

    def failed(self, ip):
        count, first = self._failures.get(ip, (0, time.monotonic()))
        self._failures[ip] = [count + 1, first]

    def deliver(self, place):
        self.received.emit(place)          # queued over to the UI thread

    # ---- what QML sees -------------------------------------------------------------------
    @pyqtSlot(str, result=str)
    def pageUrl(self, ip):
        """The link the QR code opens, for this Pi's current address."""
        return f"http://{ip}:{PORT}/send?k={self.token}" if ip else ""

    @pyqtSlot(str, result=str)
    def qrImage(self, ip):
        """A file URL of the QR code for pageUrl(ip), drawn once per address."""
        url = self.pageUrl(ip)
        if not url:
            return ""
        if url != self._qr_for:
            # A new file name per address: image links can't carry a query
            # to defeat caching.
            self._qr_path = self._qr_dir / f"baja-send-qr-{abs(hash(url)) % 100000}.png"
            qr = QrCode.encode_text(url, QrCode.Ecc.MEDIUM)
            n, scale, border = qr.get_size(), 8, 4
            size = (n + 2 * border) * scale
            img = QImage(size, size, QImage.Format.Format_RGB32)
            img.fill(QColor("white"))
            p = QPainter(img)
            for y in range(n):
                for x in range(n):
                    if qr.get_module(x, y):
                        p.fillRect((x + border) * scale, (y + border) * scale, scale, scale, QColor("black"))
            p.end()
            img.save(str(self._qr_path))
            self._qr_for = url
        return QUrl.fromLocalFile(str(self._qr_path)).toString()

    @pyqtProperty(int, constant=True)
    def port(self):
        return PORT

    @pyqtProperty(bool, constant=True)
    def listening(self):
        return self._server is not None
