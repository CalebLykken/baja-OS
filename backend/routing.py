"""Turn-by-turn directions from the offline Valhalla service
(deploy/maps/install-routing.sh), and following the route as the truck
moves: the next turn and how far it is, distance and time left, arrival,
and a new route when the truck leaves this one.

Picking a place previews the route (line, distance, time, arrival) and
guidance starts with go(), like Start in other car maps.

A route can have stops on the way (addStop): each is a leg of Valhalla's
answer, the arrival is announced and guidance carries straight on.

Valhalla runs as its own local service on 127.0.0.1:8002, so a crash
there can't take the dashboard down; requests go over plain HTTP on a
worker thread.

The route and its stops are saved in settings, so a restart (a gas stop is
a fresh boot once the key-off shutdown is on) doesn't lose it: once there's
a position and the service answers, it's worked out again, and guidance
carries on by itself if it had started. A route that ended, arrived, or
wasn't driven for a few hours stays gone.
"""

import json
import math
import re
import threading
import time
import urllib.error
import urllib.request

from PyQt6.QtCore import QObject, QTimer, pyqtProperty, pyqtSignal, pyqtSlot

from backend import safe_emit
from backend.prefs import as_bool

ROUTER = "http://127.0.0.1:8002"
OFF_ROUTE_M = 60          # this far from the line ...
OFF_ROUTE_FIXES = 3       # ... for this many fixes in a row means a new route
OFF_ROUTE_S = 1.5         # ... at least this long after the first: 1 Hz fixes still take 3, even a little
                          # early; a faster receiver waits
REROUTE_EVERY_S = 10
HEADING_MS = 2            # faster than this the GPS heading counts, and a part of the route
WRONG_WAY_DEG = 60        # ... running further off it than this counts as
WRONG_WAY_M = 40          # ... this much further away
JUMP_M = 30               # a fix can move the truck along the route this much more than it could have driven ...
JUMP_S = 1.5              # ... and for at least this long (5 Hz GPS makes 3 fixes only 0.4 s)
JUMP_FIXES = 3            # ... or further once this many in a row, moving, put it there
ARRIVED_M = 35
FAST_MS = 20              # above ~45 mph, warn about turns from further out
THEN_M = 300              # a turn this soon after the next one is shown with it
RESUME_S = 3 * 3600       # after a restart, a route saved this recently comes back ...
HERE_M = 300              # ... unless the truck is already this close to its end
RESAVE_S = 60             # while guiding, the saved route's time is kept this fresh

# Early warnings: (metres, how to say it), imperial and metric.
ALERTS = {
    False: {"near": (402, "In a quarter mile"), "far": (1609, "In 1 mile")},
    True: {"near": (400, "In 400 meters"), "far": (1500, "In one and a half kilometers")},
}

# Valhalla maneuver types -> an icon name in Icon.qml.
MANEUVER_ICONS = {
    1: "straight", 2: "turn_right", 3: "turn_left", 4: "place", 5: "place", 6: "place",
    7: "straight", 8: "straight", 9: "turn_slight_right", 10: "turn_right",
    11: "turn_sharp_right", 12: "u_turn_right", 13: "u_turn_left", 14: "turn_sharp_left",
    15: "turn_left", 16: "turn_slight_left", 17: "straight", 18: "ramp_right", 19: "ramp_left",
    20: "ramp_right", 21: "ramp_left", 22: "straight", 23: "fork_right", 24: "fork_left",
    25: "merge", 26: "roundabout_right", 27: "roundabout_right", 28: "ferry", 29: "ferry",
    37: "merge", 38: "merge",
}

ARRIVE_TYPES = (4, 5, 6)              # Valhalla maneuver types: the end of a leg


# Settings > Map > Route options: setting key -> Valhalla's auto costing option
# (0 keeps the route off that kind of road; unset is Valhalla's default).
AVOID = {"avoidFerries": "use_ferry", "avoidHighways": "use_highways", "avoidTolls": "use_tolls"}


def costing_options(settings):
    """The costing_options for a route request from what's avoided in settings."""
    if not settings:
        return {}
    auto = {opt: 0 for key, opt in AVOID.items() if as_bool(settings.get(key))}
    return {"auto": auto} if auto else {}

SHORT_MAX = 60                        # characters of on-screen instruction

TURN_WORDS = {10: "Turn right", 15: "Turn left",
              9: "Bear right", 16: "Bear left", 11: "Sharp right", 14: "Sharp left"}
KEEP_WORDS = {22: "Keep straight", 23: "Keep right", 24: "Keep left"}


def _texts(value):
    """The strings in a Valhalla list of names or {"text": ...} sign elements; junk is skipped."""
    out = []
    for e in value if isinstance(value, list) else []:
        t = e.get("text") if isinstance(e, dict) else e
        if isinstance(t, str) and t.strip():
            out.append(t.strip())
    return out


def _fit(head, names):
    """head + names, dropping trailing names (then trailing words) to stay under SHORT_MAX."""
    names = list(names)
    while len(names) > 1 and len(f"{head} {' / '.join(names)}") > SHORT_MAX:
        names.pop()
    text = f"{head} {' / '.join(names)}" if names else head
    if len(text) > SHORT_MAX:
        cut = text[:SHORT_MAX + 1]
        text = cut.rsplit(" ", 1)[0] if " " in cut else text[:SHORT_MAX]
    return text


def _ordinal(n):
    suffix = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def _fallback(m):
    return str(m.get("instruction") or "").strip().rstrip(".")


def short_instruction(m):
    """The on-screen text for a maneuver ("Exit 165B toward I-5 S"); the spoken text stays full.

    Built from Valhalla's type, street names and sign; anything it can't make a clean
    short form of keeps Valhalla's own instruction."""
    if not isinstance(m, dict):
        return ""
    try:
        return _short(m) or _fallback(m)
    except Exception:
        return _fallback(m)


def _short(m):
    kind = m.get("type")
    sign = m.get("sign") if isinstance(m.get("sign"), dict) else {}
    toward, branch = _texts(sign.get("exit_toward_elements")), _texts(sign.get("exit_branch_elements"))
    number = _texts(sign.get("exit_number_elements"))
    street = _texts(m.get("street_names")) or _texts(m.get("begin_street_names"))
    via = [("toward", toward), ("onto", branch)]
    if kind in (20, 21):
        head = "Exit " + number[0] if number else "Exit"
        for word, names in via:
            if names:
                return _fit(f"{head} {word}", names)
        return head if number else (_fit("Exit onto", street) if street else "")
    if kind in (18, 19):
        for word, names in via:
            if names:
                return _fit(f"Ramp {word}", names)
        return ""
    if kind in KEEP_WORDS:
        word = KEEP_WORDS[kind]
        for w, names in [("toward", toward), ("on" if kind == 22 else "onto", branch or street)]:
            if names:
                return _fit(f"{word} {w}", names)
        return ""
    if kind in (25, 37, 38):
        names = branch or street
        word = {37: "Merge right onto", 38: "Merge left onto"}.get(kind, "Merge onto")
        return _fit(word, names) if names else ""
    if kind in TURN_WORDS:
        # begin_street_names is the street turned onto; street_names comes after it
        names = _texts(m.get("begin_street_names")) or street
        return _fit(f"{TURN_WORDS[kind]} onto", names) if names else ""
    if kind == 26:
        count = m.get("roundabout_exit_count")
        if not isinstance(count, int) or isinstance(count, bool) or count < 1:
            return ""
        return f"Roundabout, take the {_ordinal(count)} exit"   # street_names is the circle's
    if kind in (7, 8):
        return _fit("Continue on", street) if street else ""
    return ""


FERRY_ENTER = 28                      # Valhalla maneuver type: board a ferry
FERRY_NAME = re.compile(r"^Take the (?!ferry\b)(.+) ferry\.?$", re.I)


def ferry_name(m):
    """A ferry maneuver's name: its street name, else the instruction's, else "Ferry"."""
    names = m.get("street_names")
    if isinstance(names, list) and names and isinstance(names[0], str):
        name = re.sub(r"\s+ferry$", "", names[0].strip(), flags=re.I).strip()
        if name and name.lower() != "ferry":
            return name
    found = FERRY_NAME.match(str(m.get("instruction") or "").strip())
    return found.group(1).strip() if found and found.group(1).strip() else "Ferry"


def ferry_legs(maneuvers):
    """The ferry parts of a route: [{"name", "time" (s), "length" (m)}].

    Valhalla flags them with "ferry": true (and type 28 boards one).
    Consecutive ferry maneuvers are one crossing. Never raises on odd
    data: a route must still load."""
    out, on = [], False
    for m in maneuvers:
        if not isinstance(m, dict) or (m.get("ferry") is not True and m.get("type") != FERRY_ENTER):
            on = False
            continue
        if not on or m.get("type") == FERRY_ENTER:
            out.append({"name": "Ferry", "time": 0.0, "length": 0.0})
            on = True
        leg = out[-1]
        if leg["name"] == "Ferry":
            leg["name"] = ferry_name(m)
        for key, scale in (("time", 1), ("length", 1000)):
            try:
                v = float(m.get(key) or 0) * scale   # length is in km in our request
            except (TypeError, ValueError, OverflowError):
                continue
            if math.isfinite(v):
                leg[key] += v
    return out


def tidy(text):
    """Valhalla chains spoken steps as "... Then Keep right"; lower-case the verb."""
    return re.sub(r"\bThen ([A-Z])", lambda m: "then " + m[1].lower(), text).replace(". then ", ". Then ")


def decode_polyline6(encoded):
    """Valhalla's shape: Google polyline encoding at 1e-6 precision -> [(lon, lat)]."""
    coords, index, lat, lon = [], 0, 0, 0
    while index < len(encoded):
        for which in (0, 1):
            shift = result = 0
            while True:
                b = ord(encoded[index]) - 63
                index += 1
                result |= (b & 0x1F) << shift
                shift += 5
                if b < 0x20:
                    break
            delta = ~(result >> 1) if result & 1 else result >> 1
            if which == 0:
                lat += delta
            else:
                lon += delta
        coords.append((lon / 1e6, lat / 1e6))
    return coords


def route_record(name, lon, lat, started, now, stops=()):
    """What's saved in settings for a route: JSON."""
    return json.dumps({"name": name, "lon": lon, "lat": lat, "started": started, "at": now,
                       "stops": [list(s) for s in stops]})


def saved_route(text, now):
    """The route to pick up again after a restart, from what was saved:
    {name, lon, lat, started}, plus stops [(name, lon, lat)] if it has any,
    or None if there's none or it's too old. Without its battery the Pi's
    clock can be behind after a restart, so a save that looks a little in
    the future still counts."""
    try:
        r = json.loads(text) if text else None
        if not isinstance(r, dict) or not isinstance(r.get("name"), str):
            return None
        if abs(now - float(r["at"])) > RESUME_S:
            return None
        out = {"name": r["name"], "lon": float(r["lon"]), "lat": float(r["lat"]),
               "started": r.get("started") is True}
        stops = [(str(n), float(lon), float(lat)) for n, lon, lat in r.get("stops") or []]
        if stops:
            out["stops"] = stops
        return out
    except (ValueError, TypeError, KeyError, OverflowError):
        return None


def join_legs(legs, stops):
    """Valhalla's legs as one line: (shape, maneuvers, the shape index of
    each stop, the index of each leg's first maneuver). Each leg's shape
    starts where the last one ended, and maneuvers count from their own
    leg's start. A stop's arrive maneuver says the stop's name."""
    if len(legs) != len(stops) + 1:
        raise ValueError("a leg for each stop")
    if len(legs) == 1:
        return decode_polyline6(legs[0]["shape"]), legs[0]["maneuvers"], [], [0]
    shape, maneuvers, ends, firsts = [], [], [], []
    for k, leg in enumerate(legs):
        points = decode_polyline6(leg["shape"])
        by = max(0, len(shape) - 1)
        shape += points[1:] if k else points
        firsts.append(len(maneuvers))
        for m in leg["maneuvers"]:
            m = dict(m)
            for key in ("begin_shape_index", "end_shape_index"):
                if key in m:
                    m[key] += by
            maneuvers.append(m)
        if k < len(stops):
            ends.append(len(shape) - 1)
            last = maneuvers[-1]
            if last.get("type") in ARRIVE_TYPES:
                last["instruction"] = f"Arrive at {stops[k][0]}"
                last.pop("verbal_pre_transition_instruction", None)
                last.pop("verbal_transition_alert_instruction", None)
    return shape, maneuvers, ends, firsts


def _xy(p, lat0):
    """Metres east/north of the origin, near enough for a city."""
    k = math.cos(math.radians(lat0))
    return p[0] * 111320.0 * k, p[1] * 110540.0


def _metres(a, b):
    """Straight-line distance between two (lon, lat) points, near enough."""
    (ax, ay), (bx, by) = _xy(a, a[1]), _xy(b, a[1])
    return math.hypot(bx - ax, by - ay)


def _project(p, a, b, lat0):
    """(distance from p to segment ab in metres, fraction along ab)."""
    px, py = _xy(p, lat0)
    ax, ay = _xy(a, lat0)
    bx, by = _xy(b, lat0)
    dx, dy = bx - ax, by - ay
    seg = dx * dx + dy * dy
    t = 0.0 if seg == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / seg))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy)), t


class Route:
    """One computed route and where the truck is along it."""

    def __init__(self, data, name, stops=()):
        self.name = name
        self.stops = list(stops)      # (name, lon, lat) on the way, in order
        self.shape, self.maneuvers, self.leg_ends, self._firsts = join_legs(data["trip"]["legs"], self.stops)
        self.leg = 0                  # the leg the truck is on: this many stops are behind it
        self.lat0 = self.shape[0][1]
        self.cum = [0.0]
        self.bearing = []             # each segment's compass bearing (None if it has no length)
        for a, b in zip(self.shape, self.shape[1:]):
            ax, ay = _xy(a, self.lat0)
            bx, by = _xy(b, self.lat0)
            self.cum.append(self.cum[-1] + math.hypot(bx - ax, by - ay))
            self.bearing.append(math.degrees(math.atan2(bx - ax, by - ay)) % 360
                                if (bx, by) != (ax, ay) else None)
        self.length = self.cum[-1]
        self.time = float(data["trip"]["summary"]["time"])
        self.ferries = ferry_legs(self.maneuvers) if isinstance(self.maneuvers, list) else []
        self.seg = 0                  # the shape segment the truck is on
        self.along = 0.0              # metres travelled along the route
        self.off = 0.0                # metres from the line
        self.to_end = math.inf        # metres from the end of the route, in a straight line
        self._p, self._at = None, None    # the last position it was located at, and when
        self._away = 0                # fixes in a row that put it further along (or back) than it could have got
        self._away_since = None       # when the first of those fixes came
        self._past = 0                # fixes in a row driving on beyond the next stop
        self._past_since = None

    def locate(self, lon, lat, heading=None, speed=None, now=None):
        """Snap the truck to the route, looking a little back and ahead.

        The route can come back near itself (a U-turn, a loop ramp, a
        place across a divided road), so while following it (with the
        GPS's heading and speed) this isn't just the nearest part. Moving,
        a part running the other way counts as further off. And the truck
        only moves along the route, either way, as far as it could have
        driven since the last fix, unless somewhere else on it is clearly
        where it is: what it could have got to is off-route far away, or a
        few fixes in a row while moving put it there. Without them (a new
        route, Go) it's the nearest part."""
        now = time.monotonic() if now is None else now
        p = (lon, lat)
        if speed is not None and p == self._p:
            return                    # the same fix again (the GPS also says when satellites change)
        moving = heading is not None and speed is not None and speed > HEADING_MS
        span = math.inf
        if speed is not None and self._at is not None:
            span = speed * max(0.0, now - self._at) + JUMP_M
        lo_m, hi_m = self.along - span, self.along + span
        near, far = [], []            # (metres off plus any wrong-way extra, metres off, segment, fraction)
        lo, hi = max(0, self.seg - 5), min(len(self.shape) - 1, self.seg + 150)
        for i in range(lo, hi):
            a, b = self.shape[i], self.shape[i + 1]
            extra = WRONG_WAY_M if moving and self._wrong_way(i, heading) else 0.0
            d, t = _project(p, a, b, self.lat0)
            c0, seg_m = self.cum[i], self.cum[i + 1] - self.cum[i]
            if lo_m <= c0 + t * seg_m <= hi_m:
                near.append((d + extra, d, i, t))
                continue
            far.append((d + extra, d, i, t))
            if c0 < hi_m and c0 + seg_m > lo_m:
                # The nearest point on the part of it the truck could have got to.
                t = min(max(t, (lo_m - c0) / seg_m), (hi_m - c0) / seg_m)
                c = (a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1]))
                d = _project(p, c, c, self.lat0)[0]
                near.append((d + extra, d, i, t))
        best = min(near, default=(math.inf, math.inf, self.seg, 0.0))
        jump = min(far, default=None)
        if jump and jump[0] < best[0] and jump[1] < OFF_ROUTE_M:
            if best[1] > OFF_ROUTE_M:
                best = jump           # nowhere near where it could have got, but on the route there
            elif moving:
                if not self._away:
                    self._away_since = now
                self._away += 1
                if self._away >= JUMP_FIXES and now - self._away_since >= JUMP_S:
                    best = jump
            else:
                self._away = 0        # parked, the GPS wanders: it hasn't gone anywhere
        else:
            self._away = 0
        if best is jump:
            self._away = 0
        _, self.off, self.seg, t = best
        self.along = self.cum[self.seg] + t * (self.cum[self.seg + 1] - self.cum[self.seg])
        self._p, self._at = p, now
        (px, py), (ex, ey) = _xy(p, self.lat0), _xy(self.shape[-1], self.lat0)
        self.to_end = math.hypot(ex - px, ey - py)

    def along_of(self, p, within=500.0):
        """Metres along the route to the point nearest `p` from the truck's
        segment on, or None if the route never comes within `within`."""
        best = None
        for i in range(self.seg, len(self.shape) - 1):
            d, t = _project(p, self.shape[i], self.shape[i + 1], self.lat0)
            if d <= within and (best is None or d < best[0] - 5):
                best = (d, self.cum[i] + t * (self.cum[i + 1] - self.cum[i]))
        return best[1] if best else None

    def _wrong_way(self, i, heading):
        """Segment i runs too far off the truck's heading."""
        b = self.bearing[i]
        return b is not None and abs((heading - b + 180) % 360 - 180) > WRONG_WAY_DEG

    def at_stop(self):
        """The truck has reached the next stop."""
        if self.leg >= len(self.leg_ends) or self._p is None:
            return False
        end = self.leg_ends[self.leg]
        return abs(self.along - self.cum[end]) < ARRIVED_M and _metres(self._p, self.shape[end]) < ARRIVED_M

    def _gone_by(self, heading, speed, off_max):
        """The next stop is behind the truck, which is moving the way the line
        goes and within off_max of it."""
        return not (self.leg >= len(self.leg_ends) or self.along <= self.cum[self.leg_ends[self.leg]] + ARRIVED_M
                    or self.off > off_max or speed <= HEADING_MS or self._wrong_way(self.seg, heading))

    def past_stop(self, heading, speed):
        """The truck has gone by the next stop without coming near it (a
        tunnel, a gap in the fixes). On a new route it can be put on the way
        back of an out-and-back to a stop, so it takes a few fixes in a row
        on the line, moving the way the line goes, over at least JUMP_S (by
        the time of the last locate)."""
        if not self._gone_by(heading, speed, ARRIVED_M):
            self._past = 0
            return False
        if not self._past:
            self._past_since = self._at
        self._past += 1
        return self._past >= JUMP_FIXES and (self._at is None or self._at - self._past_since >= JUMP_S)

    def passed_stop(self, heading, speed):
        """Before a reroute: the next stop is behind a truck that has since left
        the line (a frontage road 35-60 m over), which past_stop never saw. A
        reroute would turn it back for the stop. Being off the line now (it
        must be, to reroute) doesn't count against it."""
        return self._gone_by(heading, speed, math.inf)

    def stops_left(self):
        return self.stops[self.leg:]

    def next_maneuver(self):
        # Not back at a stop just reached: its arrival is over.
        for m in self.maneuvers[self._firsts[self.leg]:]:
            if self.cum[m["begin_shape_index"]] > self.along + 5:
                return m
        return self.maneuvers[-1]

    def then_maneuver(self):
        """The maneuver after the next one, when it comes right after it."""
        nxt = self.next_maneuver()
        i = self.maneuvers.index(nxt)
        if i + 1 >= len(self.maneuvers) or nxt.get("type") in ARRIVE_TYPES:
            return None                 # after a stop, the way on is for after the stop
        m = self.maneuvers[i + 1]
        gap = self.cum[m["begin_shape_index"]] - self.cum[nxt["begin_shape_index"]]
        return m if gap < THEN_M else None

    @property
    def remaining(self):
        return max(0.0, self.length - self.along)

    def time_left(self):
        """Seconds still to drive: each maneuver carries its own time, so a
        fast road first and slow streets last aren't averaged out. The one
        the truck is on counts for the share of it still ahead."""
        total = 0.0
        for m in self.maneuvers:
            try:
                t = float(m["time"])
                a = self.cum[m["begin_shape_index"]]
                b = self.cum[m["end_shape_index"]]
            except (KeyError, TypeError, ValueError, IndexError):
                return self.time * self.remaining / self.length if self.length > 0 else 0.0
            if b <= self.along:
                continue
            total += t if a >= self.along or b <= a else t * (b - self.along) / (b - a)
        return total


class Router(QObject):
    changed = pyqtSignal()          # route started/ended, computing, availability
    progressChanged = pyqtSignal()  # where the truck is along the route
    optionsChanged = pyqtSignal()   # an avoid-ferries/highways/tolls setting
    stopsChanged = pyqtSignal()     # a stop added, removed or reached
    stopsFailed = pyqtSignal(str)   # a stop couldn't be added or taken off: why, to show
    speak = pyqtSignal(str)         # a spoken direction (connected to Voice.say)
    resumed = pyqtSignal(str, float, float)     # a preview from before a restart is back
    _got = pyqtSignal(object, str, str, bool, int)   # response, error, destination name, reroute, request number
    _status = pyqtSignal(bool)

    def __init__(self, gps, settings=None, parent=None):
        super().__init__(parent)
        self._gps = gps
        self._settings = settings
        self._spoken = set()          # (maneuver index, "alert"/"turn") already said
        self._last_said = ""          # the last direction said, for repeatLast()
        self._started = False         # guidance running (False: just a preview)
        self._available = False
        self._route = None
        self._dest = None             # (name, lon, lat)
        self._stops = []              # (name, lon, lat) not reached yet, in order, before _dest
        self._stops_failed = ""       # what to show if the route asked for with changed stops doesn't come
        self._computing = False
        self._gen = 0                 # number of the latest request; older answers are dropped
        self._error = ""
        self._off_count = 0
        self._off_since = 0.0         # when the current run of off-route fixes began
        self._clock = time.monotonic  # for off-route timing (tests use a fake one)
        self._last_reroute = 0.0
        self._arrived = False
        # The route from before a restart, until it can be asked for again,
        # then while that answer is on its way.
        self._resume = saved_route(str(settings.get("route", "")), time.time()) if settings else None
        self._resuming = None
        self._saved_at = 0.0
        self._got.connect(self._on_route)
        self._status.connect(self._on_status)
        self._check_timer = QTimer(self, interval=30000, timeout=self._check)
        gps.fixChanged.connect(self._on_fix)    # new positions only, not status updates
        gps.changed.connect(self._on_gps_changed)

    def start(self):
        self._check()
        self._check_timer.start()

    # ---- is the service there? ---------------------------------------------------
    def _check(self):
        def work():
            try:
                with urllib.request.urlopen(ROUTER + "/status", timeout=3) as r:
                    ok = r.status == 200
            except (OSError, urllib.error.URLError):
                ok = False
            safe_emit(self, "_status", ok)
        threading.Thread(target=work, daemon=True).start()

    def _on_status(self, ok):
        if ok != self._available:
            self._available = ok
            self.changed.emit()
        self._resume_if_ready()

    # ---- kept between runs ----------------------------------------------------------
    def _save(self):
        """Save the destination, its stops and whether guidance is on, with the time."""
        if self._settings and self._dest:
            name, lon, lat = self._dest
            self._settings.set("route", route_record(name, lon, lat, self._started, time.time(), self._stops))
            self._saved_at = time.monotonic()

    def _forget(self):
        self._resume = self._resuming = None
        if self._settings:
            self._settings.set("route", "")

    def _resume_if_ready(self):
        """Ask for the route from before the restart again, once there's a
        position and the service answers."""
        r = self._resume
        if not r or not self._available or not self._gps.hasFix or self._gps.stale:
            return
        self._resume = None
        if self._dest:
            return                                  # a new place was picked meanwhile
        stops = r.get("stops", [])
        if not stops and _metres((self._gps.lon, self._gps.lat), (r["lon"], r["lat"])) < HERE_M:
            print(f"Maps: already at {r['name']}; not resuming the route")
            self._forget()
            return
        print(f"Maps: resuming the route to {r['name']}")
        self._route_to(r["name"], r["lon"], r["lat"], stops)    # saved as it was, time and all
        self._resuming = r

    # ---- asking for a route ---------------------------------------------------------
    def _request(self, name, lon, lat, reroute=False):
        self._gen += 1              # any answer still on its way is out of date now
        gen = self._gen
        if not self._gps.hasFix:
            self._computing = False
            self._error = "Waiting for the truck's position"
            self.changed.emit()
            return
        start = {"lon": self._gps.lon, "lat": self._gps.lat, "type": "break"}
        if self._gps.speed > 2:
            # Leave in the direction the truck is already going.
            start.update(heading=round(self._gps.heading), heading_tolerance=45)
        places = [(s[1], s[2]) for s in self._stops] + [(lon, lat)]
        request = {
            "locations": [start] + [{"lon": x, "lat": y, "type": "break"} for x, y in places],
            "costing": "auto",
            "directions_options": {"units": "kilometers", "language": "en-US"},
        }
        options = costing_options(self._settings)
        if options:
            request["costing_options"] = options
        body = json.dumps(request).encode()
        self._computing = True
        self._error = ""
        self.changed.emit()

        def work():
            data, error = None, "Couldn't get a route"
            try:
                req = urllib.request.Request(ROUTER + "/route", data=body,
                                             headers={"Content-Type": "application/json"})
                with urllib.request.urlopen(req, timeout=20) as r:
                    data, error = json.loads(r.read()), ""
            except urllib.error.HTTPError as e:
                try:
                    reply = json.loads(e.read())
                except (OSError, ValueError):
                    reply = None
                msg = reply.get("error") if isinstance(reply, dict) else None
                error = msg if isinstance(msg, str) and msg else "No route found"
            except (OSError, urllib.error.URLError, ValueError):
                error = "Routing isn't running"
            finally:
                # Always, or _computing would never clear. Anything unexpected
                # is logged by threading.excepthook (main.py) on the way out.
                safe_emit(self, "_got", None if error else data, error, name, reroute, gen)
        threading.Thread(target=work, name="route", daemon=True).start()

    def _on_route(self, data, error, name, reroute, gen):
        if gen != self._gen:
            return      # cancelled, or a newer place or reroute was asked for since
        self._computing = False
        resumed = None if reroute else self._resuming
        if not reroute:
            self._resuming = None
        route = None
        if not error:
            try:
                route = Route(data, name, self._stops)
                if not isinstance(route.maneuvers, list) or not route.maneuvers:
                    raise ValueError("no maneuvers")
            except (KeyError, IndexError, TypeError, ValueError, AttributeError):
                # Not a route this code can follow (a changed or broken router).
                print(f"Maps: couldn't read the route to {name}")
                route, error = None, "Couldn't read the route"
        if route is None:
            self._error = ("No road route to there" if "No path" in error or "No suitable" in error
                           else error)
            if resumed:
                # Nobody asked for it this run, so there's nowhere to show why.
                print(f"Maps: couldn't resume the route to {name} ({self._error})")
                self.stop()
                return
            if not reroute:
                self._route = None
            elif self._route and not self._arrived:
                # The old line stays, so the stops it goes to do too: one
                # with no road to it mustn't stop every later reroute.
                self._set_stops(self._route.stops_left())
                self._save()
                if self._stops_failed:
                    self.stopsFailed.emit(self._stops_failed)
            self._stops_failed = ""
            self.changed.emit()
            return
        self._stops_failed = ""
        self._route = route
        self._arrived = False
        self._off_count = 0
        self._spoken = set()
        self._route.locate(self._gps.lon, self._gps.lat)
        if reroute and self._started and not self._gps.stale:
            self._begin("Rerouting. ")
        if resumed and resumed["started"]:
            self._go(f"Continuing to {self._stops[0][0] if self._stops else name}. ")
        elif resumed:
            self.resumed.emit(name, resumed["lon"], resumed["lat"])
        self.changed.emit()
        self.progressChanged.emit()

    def _begin(self, prefix=""):
        """Guidance starts (or restarts on a new route): say the first step."""
        first = self._route.maneuvers[0]
        self._say(prefix + (first.get("verbal_pre_transition_instruction") or first.get("instruction") or ""))
        self._spoken.add((0, "turn"))
        if self._gps.source == "demo":
            self._gps.followPath(self._route.shape)     # the simulated truck drives it

    @pyqtSlot()
    def go(self):
        """Start guidance on the previewed route."""
        self._go()

    def _go(self, prefix=""):
        if self._route and not self._started:
            self._started = True
            self._route.locate(self._gps.lon, self._gps.lat)
            self._begin(prefix)
            self._save()
            self.changed.emit()
            self.progressChanged.emit()

    def _say(self, text):
        if text:
            self._last_said = tidy(text)
            self.speak.emit(self._last_said)

    @pyqtSlot()
    def repeatLast(self):
        """Say the last direction again (a missed prompt over road noise).
        Before anything has been said, the next turn. Nothing without guidance."""
        r = self._route
        if not r or not self._started:
            return
        if not self._last_said and not self._arrived:
            m = r.next_maneuver()
            self._say(m.get("verbal_pre_transition_instruction") or m.get("instruction") or "")
            return
        if self._last_said:
            self.speak.emit(self._last_said)

    def _prompt(self, r):
        """Say the next turn twice: an early warning, then just before it."""
        m = r.next_maneuver()
        i = r.maneuvers.index(m)
        if m.get("type") in ARRIVE_TYPES:
            return                                  # arrival is announced on its own
        dist = max(0.0, r.cum[m["begin_shape_index"]] - r.along)
        speed = self._gps.speed
        metric = bool(self._settings) and as_bool(self._settings.get("metric"))
        warn_m, warn_words = ALERTS[metric]["far" if speed > FAST_MS else "near"]
        turn_m = max(60.0, speed * 6)               # about six seconds before the turn
        alert = (m.get("verbal_transition_alert_instruction") or m.get("instruction") or "").rstrip(".")
        if (i, "alert") not in self._spoken and turn_m * 2 < dist <= warn_m:
            # Only if the turn was further than this when it came up; on a
            # short stretch the "turn now" line is enough.
            self._spoken.add((i, "alert"))
            if alert:
                self._say(f"{warn_words}, {alert[0].lower()}{alert[1:]}.")
        if (i, "turn") not in self._spoken and dist <= turn_m:
            self._spoken.add((i, "turn"))
            self._spoken.add((i, "alert"))
            self._say(m.get("verbal_pre_transition_instruction") or m.get("instruction") or "")

    # ---- route options ----------------------------------------------------------------
    def _avoids(self, key):
        return bool(self._settings) and as_bool(self._settings.get(key))

    @pyqtProperty(bool, notify=optionsChanged)
    def avoidFerries(self):
        return self._avoids("avoidFerries")

    @pyqtProperty(bool, notify=optionsChanged)
    def avoidHighways(self):
        return self._avoids("avoidHighways")

    @pyqtProperty(bool, notify=optionsChanged)
    def avoidTolls(self):
        return self._avoids("avoidTolls")

    @pyqtSlot(str, bool)
    def setAvoid(self, key, on):
        """Turn an avoid option on or off ("avoidFerries", "avoidHighways",
        "avoidTolls"). A route already shown or being driven is asked for
        again with it, and so is one that couldn't be found (the option may
        be why): the old line stays until the new one arrives, and stays if
        no route can be found that way. Not after arriving: that's over."""
        if key not in AVOID or not self._settings or self._avoids(key) == on:
            return
        self._settings.set(key, "true" if on else "false")
        self.optionsChanged.emit()
        if self._dest and not self._arrived:
            self._request(*self._dest, reroute=self._route is not None)

    # ---- stops on the way ------------------------------------------------------------
    def _set_stops(self, stops):
        stops = list(stops)
        if stops != self._stops:
            self._stops = stops
            self.stopsChanged.emit()

    def _change_stops(self, stops, failed):
        """Ask for the route with these stops; True if it was asked for. The
        old line stays until the new one arrives, and stays with its stops
        if none can be found, which stopsFailed tells with `failed`."""
        if not self._route or self._arrived or not self._gps.hasFix:
            self.stopsFailed.emit(failed)
            return False
        self._set_stops(stops)
        self._request(*self._dest, reroute=True)
        self._stops_failed = failed
        self._save()
        return True

    @pyqtSlot(str, float, float, result=bool)
    def addStop(self, name, lon, lat):
        """A stop after the others, before the destination of the route shown."""
        at = len(self._stops)
        r = self._route
        if r and [tuple(s) for s in self._stops] == [tuple(s) for s in r.stops[r.leg:]]:
            pos = r.along_of((lon, lat))
            if pos is not None:         # in the order the route reaches them
                at = sum(1 for k in range(len(self._stops)) if r.cum[r.leg_ends[r.leg + k]] < pos)
        return self._change_stops(self._stops[:at] + [(name, lon, lat)] + self._stops[at:],
                                  f"Couldn't add {name}")

    @pyqtSlot(int, result=bool)
    def removeStop(self, index):
        if not 0 <= index < len(self._stops):
            return False
        return self._change_stops(self._stops[:index] + self._stops[index + 1:],
                                  f"Couldn't skip {self._stops[index][0]}")

    def _leave_stop(self, r):
        """The next stop is behind the truck: it's off the list, the rest
        stay. Returns the stop."""
        stop = r.stops[r.leg]
        r.leg += 1
        stops = list(self._stops)
        if stop in stops:                           # unless taken off a moment ago
            stops.remove(stop)
        self._set_stops(stops)
        self._save()
        return stop

    def _reach_stop(self, r):
        """Arrived at a stop: say so and carry on, no Go needed."""
        stop = self._leave_stop(r)
        self._say(f"You have arrived at {stop[0]}. Continuing to {(self._stops or [self._dest])[0][0]}.")
        if self._computing:
            self._request(*self._dest, reroute=True)    # that answer would come back to this stop

    @pyqtSlot(str, float, float)
    def routeTo(self, name, lon, lat):
        """Work out a route to preview (a new place replaces any route)."""
        self._resume = self._resuming = None
        self._route_to(name, lon, lat)
        self._save()

    def _route_to(self, name, lon, lat, stops=()):
        if self._started:
            self._gps.clearPath()
        self._started = False
        self._route = None
        self._last_said = ""
        self._dest = (name, lon, lat)
        self._set_stops(stops)
        self._stops_failed = ""
        self._request(name, lon, lat)

    @pyqtSlot()
    def stop(self):
        self._gps.clearPath()
        self._started = False
        self._route = None
        self._last_said = ""
        self._dest = None
        self._set_stops([])
        self._stops_failed = ""
        self._error = ""
        self._computing = False
        self._gen += 1              # an answer still on its way is for a route nobody wants
        self._forget()
        self.changed.emit()
        self.progressChanged.emit()

    # ---- following it --------------------------------------------------------------
    def _on_gps_changed(self):
        # The fix going stale (a tunnel) brings no new fix: end any run of
        # off-route fixes there, so the first rough fixes after it don't
        # finish it off.
        if self._gps.stale and self._off_count:
            self._off_count = 0
            self.progressChanged.emit()

    def _on_fix(self):
        if self._resume:
            self._resume_if_ready()
        r = self._route
        if not r or not self._started or not self._gps.hasFix:
            return
        if self._gps.stale:
            # The receiver's last position, held while it has no sky (a
            # tunnel, a garage): nothing new to follow, so no reroute and
            # nothing said until it's back.
            if self._off_count:
                self._off_count = 0
                self.progressChanged.emit()
            return
        now = self._clock()
        r.locate(self._gps.lon, self._gps.lat, self._gps.heading, self._gps.speed, now)
        if r.remaining < ARRIVED_M and r.to_end < ARRIVED_M and not self._arrived:
            self._arrived = True
            self._forget()                          # shown a little longer, but done
            self._say(f"You have arrived at {r.name}.")
            QTimer.singleShot(20000, lambda: self.stop() if self._arrived else None)
        elif not self._arrived:
            while not self._computing and r.past_stop(self._gps.heading, self._gps.speed):
                self._leave_stop(r)                 # nothing to announce: it wasn't reached
            if r.at_stop():
                self._reach_stop(r)
            else:
                self._prompt(r)
            if time.monotonic() - self._saved_at > RESAVE_S:
                self._save()                        # still being driven
        if r.off > OFF_ROUTE_M and not self._arrived:
            if not self._off_count:
                self._off_since = now
            self._off_count += 1
            # A receiver reporting several times a second would otherwise
            # reroute after a fraction of a second off the line.
            if (self._off_count >= OFF_ROUTE_FIXES and now - self._off_since >= OFF_ROUTE_S
                    and not self._computing
                    and now - self._last_reroute > REROUTE_EVERY_S and self._dest):
                self._last_reroute = now
                while r.passed_stop(self._gps.heading, self._gps.speed):
                    self._leave_stop(r)
                self._request(*self._dest, reroute=True)
        else:
            self._off_count = 0
        self.progressChanged.emit()

    # ---- what QML sees ------------------------------------------------------------
    @pyqtProperty(bool, notify=changed)
    def available(self):
        return self._available

    @pyqtProperty(bool, notify=changed)
    def active(self):
        """Guidance is running."""
        return self._route is not None and self._started

    @pyqtProperty(bool, notify=changed)
    def previewing(self):
        """A route is computed and shown, waiting for Go."""
        return self._route is not None and not self._started

    @pyqtProperty(bool, notify=changed)
    def computing(self):
        return self._computing

    @pyqtProperty(str, notify=changed)
    def error(self):
        return self._error

    @pyqtProperty(str, notify=changed)
    def destinationName(self):
        return self._route.name if self._route else (self._dest[0] if self._dest else "")

    @pyqtProperty("QVariantList", notify=changed)
    def shape(self):
        """The route as [[lon, lat], ...] for the map."""
        return [list(p) for p in self._route.shape] if self._route else []

    @pyqtProperty("QVariantList", notify=changed)
    def ferries(self):
        """The ferry crossings on the route: [{name, minutes}], minutes 0 when unknown."""
        if not self._route:
            return []
        return [{"name": f["name"], "minutes": max(1, round(f["time"] / 60)) if f["time"] > 0 else 0}
                for f in self._route.ferries]

    @pyqtProperty("QVariantList", notify=stopsChanged)
    def stops(self):
        """The stops still ahead, in order: [{name, lon, lat}]."""
        return [{"name": n, "lon": x, "lat": y} for n, x, y in self._stops]

    @pyqtProperty(int, notify=stopsChanged)
    def stopCount(self):
        return len(self._stops)

    @pyqtProperty(str, notify=stopsChanged)
    def nextStopName(self):
        """The stop the truck is heading to, "" if it's the destination."""
        return self._stops[0][0] if self._stops else ""

    @pyqtProperty(bool, notify=progressChanged)
    def arrived(self):
        return self._arrived

    @pyqtProperty(str, notify=progressChanged)
    def instruction(self):
        if not self._route:
            return ""
        if self._arrived:
            return "You've arrived at " + self._route.name
        # The short form on screen; the spoken form chains the next step.
        return short_instruction(self._route.next_maneuver())

    @pyqtProperty(str, notify=progressChanged)
    def maneuverIcon(self):
        if not self._route:
            return ""
        if self._arrived:
            return "place"
        return MANEUVER_ICONS.get(self._route.next_maneuver().get("type"), "straight")

    @pyqtProperty(str, notify=progressChanged)
    def thenIcon(self):
        """The turn right after the next one, if it's close ("Then ↰"), else ''."""
        m = self._route.then_maneuver() if self._route and not self._arrived else None
        return MANEUVER_ICONS.get(m.get("type"), "straight") if m else ""

    @pyqtProperty(float, notify=progressChanged)
    def distanceToTurn(self):
        """Metres to the next maneuver."""
        r = self._route
        if not r:
            return 0.0
        m = r.next_maneuver()
        return max(0.0, r.cum[m["begin_shape_index"]] - r.along)

    @pyqtProperty(int, notify=progressChanged)
    def segment(self):
        """The route segment the truck is on (the map draws the line from there)."""
        return self._route.seg if self._route else 0

    @pyqtProperty(float, notify=progressChanged)
    def alongSegment(self):
        """Metres the truck is along that segment."""
        r = self._route
        return max(0.0, r.along - r.cum[r.seg]) if r else 0.0

    @pyqtProperty(float, notify=progressChanged)
    def remainingDistance(self):
        return self._route.remaining if self._route else 0.0

    @pyqtProperty(float, notify=progressChanged)
    def remainingTime(self):
        """Seconds, from Valhalla's time for each part still ahead."""
        return self._route.time_left() if self._route else 0.0

    @pyqtProperty(bool, notify=progressChanged)
    def offRoute(self):
        return bool(self._route and self._off_count > 0)
