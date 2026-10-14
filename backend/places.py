"""Offline place search: every named place, point of interest and street
in the installed map, in a small SQLite full-text index.

The index is built once from the map itself (basemap.pmtiles), so search
needs no internet and no extra download:

    python3 -m backend.places build ~/.local/share/baja-os/maps
    python3 -m backend.places search ~/.local/share/baja-os/maps "gas works"

install-map.sh builds it after each map download. Everything here is plain
Python (gzip, sqlite3): a minimal PMTiles v3 reader and Mapbox Vector Tile
decoder, enough to pull out names and positions.
"""

import gzip
import math
import sqlite3
import struct
import sys
import time
from pathlib import Path

INDEX_NAME = "places.sqlite"

# What gets indexed from each layer of the Protomaps basemap, and a weight
# for ranking (lower comes first when names match equally well).
PLACE_KINDS = {"locality": 0, "macrohood": 1, "neighbourhood": 1, "region": 3, "country": 4}
ROAD_KINDS = {"highway": 1, "major_road": 1, "minor_road": 2, "other": 3}
# Stops share names with what they serve ("University of Washington");
# rank them after the place itself.
TRANSIT_KINDS = {"stop", "station", "halt", "tram_stop", "ferry_terminal", "parking_entrance"}
# Map features that aren't somewhere you'd drive to.
SKIP_POI_KINDS = {"bench", "drinking_water", "toilets", "post_box", "waste_basket",
                  "bicycle_parking", "atm", "vending_machine", "information", "bus_stop",
                  "grass", "scrub", "traffic_signals", "administrative", "industrial",
                  "residential", "site", "construction", "crossing", "street_lamp", "tree",
                  "wood", "forest", "farmland", "meadow", "allotments", "brownfield",
                  "greenfield", "cliff", "peak", "bay", "strait", "water", "wetland",
                  "railway", "platform", "stop_position", "subway_entrance", "level_crossing"}


# ---- PMTiles v3 ---------------------------------------------------------------

def _varint(buf, pos):
    result = shift = 0
    while True:
        b = buf[pos]
        pos += 1
        result |= (b & 0x7F) << shift
        if not b & 0x80:
            return result, pos
        shift += 7


def _decompress(data, kind):
    if kind in (0, 1):            # unknown / none
        return data
    if kind == 2:
        return gzip.decompress(data)
    raise ValueError(f"unsupported PMTiles compression {kind}")


def _hilbert_to_xy(z, d):
    n = 1 << z
    x = y = 0
    s = 1
    t = d
    while s < n:
        rx = 1 & (t // 2)
        ry = 1 & (t ^ rx)
        if ry == 0:
            if rx == 1:
                x, y = s - 1 - x, s - 1 - y
            x, y = y, x
        x += s * rx
        y += s * ry
        t //= 4
        s *= 2
    return x, y


def tile_id_to_zxy(tile_id):
    acc = 0
    for z in range(32):
        count = 1 << (2 * z)
        if tile_id < acc + count:
            x, y = _hilbert_to_xy(z, tile_id - acc)
            return z, x, y
        acc += count
    raise ValueError("tile id out of range")


class PMTiles:
    """Read-only access to a local .pmtiles archive."""

    def __init__(self, path):
        self.f = open(path, "rb")
        h = self.f.read(127)
        if h[:7] != b"PMTiles" or h[7] != 3:
            raise ValueError("not a PMTiles v3 archive")
        (self.root_off, self.root_len, _meta_off, _meta_len, self.leaf_off, _leaf_len,
         self.data_off, _data_len) = struct.unpack("<8Q", h[8:72])
        self.internal = h[97]
        self.tile_comp = h[98]
        self.max_zoom = h[101]

    def _read(self, off, length):
        self.f.seek(off)
        return self.f.read(length)

    def _directory(self, off, length):
        buf = _decompress(self._read(off, length), self.internal)
        n, pos = _varint(buf, 0)
        ids, runs, lens, offs = [], [], [], []
        last = 0
        for _ in range(n):
            v, pos = _varint(buf, pos)
            last += v
            ids.append(last)
        for _ in range(n):
            v, pos = _varint(buf, pos)
            runs.append(v)
        for _ in range(n):
            v, pos = _varint(buf, pos)
            lens.append(v)
        for i in range(n):
            v, pos = _varint(buf, pos)
            offs.append(offs[i - 1] + lens[i - 1] if v == 0 and i > 0 else v - 1)
        return list(zip(ids, runs, lens, offs))

    def entries(self):
        """Every (tile_id, run_length, length, offset) tile entry."""
        stack = [(self.root_off, self.root_len)]
        while stack:
            off, length = stack.pop()
            for tid, run, ln, o in self._directory(off, length):
                if run == 0:
                    stack.append((self.leaf_off + o, ln))
                else:
                    yield tid, run, ln, o

    def tile(self, length, offset):
        return _decompress(self._read(self.data_off + offset, length), self.tile_comp)


# ---- Mapbox Vector Tiles ------------------------------------------------------------

def _fields(buf, pos=0, end=None):
    """Yield (field number, wire type, value) from a protobuf message.
    Length-delimited values come back as (start, end) offsets."""
    end = len(buf) if end is None else end
    while pos < end:
        key, pos = _varint(buf, pos)
        field, wire = key >> 3, key & 7
        if wire == 0:
            v, pos = _varint(buf, pos)
        elif wire == 2:
            ln, pos = _varint(buf, pos)
            v = (pos, pos + ln)
            pos += ln
        elif wire == 5:
            v = buf[pos:pos + 4]
            pos += 4
        elif wire == 1:
            v = buf[pos:pos + 8]
            pos += 8
        else:
            raise ValueError("bad wire type")
        yield field, wire, v


def _packed(buf, span):
    pos, end = span
    out = []
    while pos < end:
        v, pos = _varint(buf, pos)
        out.append(v)
    return out


def _value(buf, span):
    for field, _wire, v in _fields(buf, *span):
        if field == 1:
            return bytes(buf[v[0]:v[1]]).decode("utf-8", "replace")
        if field == 2:
            return struct.unpack("<f", v)[0]
        if field == 3:
            return struct.unpack("<d", v)[0]
        if field in (4, 5):
            return v
        if field == 6:
            return (v >> 1) ^ -(v & 1)
        if field == 7:
            return bool(v)
    return None


def _anchor(geom):
    """A representative point: the first point, or a line's middle vertex."""
    pts = []
    x = y = 0
    i = 0
    while i < len(geom):
        cmd, count = geom[i] & 7, geom[i] >> 3
        i += 1
        if cmd in (1, 2):
            for _ in range(count):
                dx, dy = geom[i], geom[i + 1]
                i += 2
                x += (dx >> 1) ^ -(dx & 1)
                y += (dy >> 1) ^ -(dy & 1)
                pts.append((x, y))
        # ClosePath (7) has no parameters
    if not pts:
        return None
    return pts[len(pts) // 2]


def read_layers(data, wanted):
    """{layer name: [(properties, (x, y) anchor in tile units, extent)]} for `wanted` layers."""
    buf = memoryview(data)
    out = {}
    for field, _wire, span in _fields(buf):
        if field != 3:
            continue
        name, extent, keys, values, feats = None, 4096, [], [], []
        for f, _w, v in _fields(buf, *span):
            if f == 1:
                name = bytes(buf[v[0]:v[1]]).decode()
                if name not in wanted:
                    break
            elif f == 5:
                extent = v
            elif f == 3:
                keys.append(bytes(buf[v[0]:v[1]]).decode())
            elif f == 4:
                values.append(v)
            elif f == 2:
                feats.append(v)
        if name not in wanted:
            continue
        rows = []
        for fspan in feats:
            tags, geom = [], []
            for f, _w, v in _fields(buf, *fspan):
                if f == 2:
                    tags = _packed(buf, v)
                elif f == 4:
                    geom = _packed(buf, v)
            props = {}
            for k, vi in zip(tags[0::2], tags[1::2]):
                props[keys[k]] = values[vi]
            if "name" not in props:
                continue
            props = {k: _value(buf, v) for k, v in props.items() if k in ("name", "kind", "ref", "pmap:kind")}
            pt = _anchor(geom)
            if pt:
                rows.append((props, pt, extent))
        out[name] = rows
    return out


def to_lonlat(z, x, y, px, py, extent):
    n = 1 << z
    lon = (x + px / extent) / n * 360.0 - 180.0
    lat = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * (y + py / extent) / n))))
    return lon, lat


# ---- building the index -------------------------------------------------------

def build(maps_dir, log=print):
    maps_dir = Path(maps_dir)
    pm = PMTiles(maps_dir / "basemap.pmtiles")
    started = time.time()
    places, pois, roads = {}, {}, {}
    entries = [e for e in pm.entries()]
    top = pm.max_zoom
    done = 0
    for tid, run, ln, off in entries:
        z, x, y = tile_id_to_zxy(tid)
        # Place labels from every zoom (some only appear at low zoom);
        # points of interest and streets from the most detailed tiles.
        wanted = {"places"} | ({"pois", "roads"} if z == top else set())
        if z < 10 or (z != top and z % 2):
            continue
        layers = read_layers(pm.tile(ln, off), wanted)
        for props, (px, py), extent in layers.get("places", []):
            kind = props.get("kind", "")
            if kind in PLACE_KINDS:
                lon, lat = to_lonlat(z, x, y, px, py, extent)
                places.setdefault((props["name"], kind), (lon, lat))
        for props, (px, py), extent in layers.get("pois", []):
            kind = props.get("kind", "")
            if kind in SKIP_POI_KINDS:
                continue
            lon, lat = to_lonlat(z, x, y, px, py, extent)
            pois.setdefault((props["name"], round(lon, 3), round(lat, 3)), (kind, lon, lat))
        for props, (px, py), extent in layers.get("roads", []):
            kind = props.get("kind", "")
            if kind not in ROAD_KINDS:
                continue
            lon, lat = to_lonlat(z, x, y, px, py, extent)
            # One entry per street per ~1.5 km, so long streets show up in
            # each area they pass through.
            roads.setdefault((props["name"], round(lon * 60), round(lat * 60)), (kind, lon, lat))
        done += 1
        if done % 2000 == 0:
            log(f"   {done} tiles read")

    # Each result says which neighbourhood it's in.
    hoods = [(n, lon, lat) for (n, k), (lon, lat) in places.items() if k in ("neighbourhood", "macrohood", "locality")]
    grid = {}
    for h in hoods:
        grid.setdefault((round(h[1] * 20), round(h[2] * 20)), []).append(h)

    def area(lon, lat):
        best, bd = "", 1e9
        gx, gy = round(lon * 20), round(lat * 20)
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for n, hl, ht in grid.get((gx + dx, gy + dy), ()):
                    d = (hl - lon) ** 2 * 0.45 + (ht - lat) ** 2
                    if d < bd:
                        best, bd = n, d
        return best

    tmp = maps_dir / (INDEX_NAME + ".tmp")
    tmp.unlink(missing_ok=True)
    db = sqlite3.connect(tmp)
    db.execute("CREATE VIRTUAL TABLE places USING fts5(name, kind UNINDEXED, area UNINDEXED,"
               " weight UNINDEXED, lon UNINDEXED, lat UNINDEXED, tokenize='unicode61 remove_diacritics 2')")
    rows = []
    for (name, kind), (lon, lat) in places.items():
        rows.append((name, kind, "", PLACE_KINDS[kind], lon, lat))
    for (name, _, _), (kind, lon, lat) in pois.items():
        rows.append((name, kind, area(lon, lat), 2 if kind in TRANSIT_KINDS else 1, lon, lat))
    for (name, _, _), (kind, lon, lat) in roads.items():
        rows.append((name, "street", area(lon, lat), ROAD_KINDS[kind], lon, lat))
    db.executemany("INSERT INTO places VALUES (?, ?, ?, ?, ?, ?)", rows)
    db.commit()
    db.execute("INSERT INTO places(places) VALUES('optimize')")
    db.commit()
    db.close()
    tmp.replace(maps_dir / INDEX_NAME)
    log(f"Indexed {len(places)} places, {len(pois)} points of interest and "
        f"{len(roads)} street sections in {time.time() - started:.0f} s")


# ---- searching ------------------------------------------------------------------

def _fts_query(text):
    words = [w for w in "".join(c if c.isalnum() else " " for c in text.lower()).split() if w]
    return " AND ".join(f'"{w}"*' for w in words)


def search(db, text, near=None, limit=12):
    """Best matches for `text`, nearest first among equally good names.
    `near` is (lon, lat) to measure distance from."""
    q = _fts_query(text)
    if not q:
        return []
    rows = db.execute("SELECT name, kind, area, weight, lon, lat, bm25(places) FROM places"
                      " WHERE places MATCH ? ORDER BY bm25(places) LIMIT 300", (q,)).fetchall()
    t = text.strip().lower()
    out, seen = [], set()
    for name, kind, area_, weight, lon, lat, score in rows:
        dist = None
        if near:
            dx = (lon - near[0]) * 111320 * math.cos(math.radians(lat))
            dy = (lat - near[1]) * 110540
            dist = math.hypot(dx, dy)
        starts = name.lower().startswith(t)
        exact = name.lower() == t
        key = (name, area_)
        if key in seen:
            continue
        seen.add(key)
        # Exact names first; after that one score that balances how well the
        # name matches (starts with what was typed, close to it in length),
        # how important the place is, and how far away it is, so a
        # "Home Depot Garden Center" 50 km away loses to "The Home Depot"
        # 3 km away.
        extra = (len(name) - len(t)) // 8
        blended = (0 if starts else 1.5) + weight + 0.8 * extra + (dist or 0) / 8000
        order = (0 if exact else 1, blended, score)
        out.append((order, {"name": name, "kind": kind, "area": area_, "lon": lon, "lat": lat,
                            "distance": dist if dist is not None else -1}))
    out.sort(key=lambda r: r[0])
    return [r[1] for r in out[:limit]]


if __name__ == "__main__":
    cmd, folder = sys.argv[1], Path(sys.argv[2]).expanduser()
    if cmd == "build":
        build(folder)
    elif cmd == "search":
        con = sqlite3.connect(folder / INDEX_NAME)
        for r in search(con, " ".join(sys.argv[3:]), near=(-122.3321, 47.6062)):
            print(f"{r['name']:40} {r['kind']:14} {r['area']:24} {r['distance'] / 1000:6.1f} km")
