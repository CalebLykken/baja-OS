"""Build controls.geojson: every traffic light, stop sign and yield sign in
the installed map's area, for the map to draw (like Apple Maps does), from
the OpenStreetMap extract that install-routing.sh downloads.

    venv/bin/python build_controls.py washington-latest.osm.pbf MAPS_DIR
"""

import json
import sys
import time
from pathlib import Path

import osmium

KINDS = {"traffic_signals": "signal", "stop": "stop", "give_way": "yield"}


class Controls(osmium.SimpleHandler):
    def __init__(self, bbox):
        super().__init__()
        self.w, self.s, self.e, self.n = bbox
        self.features = []

    def node(self, n):
        kind = KINDS.get(n.tags.get("highway"))
        if not kind or not n.location.valid():
            return
        lon, lat = n.location.lon, n.location.lat
        if self.w <= lon <= self.e and self.s <= lat <= self.n:
            self.features.append({"type": "Feature", "properties": {"k": kind},
                                  "geometry": {"type": "Point", "coordinates": [round(lon, 6), round(lat, 6)]}})


def main():
    pbf, maps_dir = sys.argv[1], Path(sys.argv[2]).expanduser()
    region = json.loads((maps_dir / "region.json").read_text())
    started = time.time()
    h = Controls(region["bbox"])
    h.apply_file(pbf)
    out = maps_dir / "controls.geojson"
    tmp = out.with_suffix(".tmp")
    tmp.write_text(json.dumps({"type": "FeatureCollection", "features": h.features}, separators=(",", ":")))
    tmp.replace(out)
    counts = {k: sum(1 for f in h.features if f["properties"]["k"] == k) for k in KINDS.values()}
    print(f"Found {counts['signal']} traffic lights, {counts['stop']} stop signs and "
          f"{counts['yield']} yield signs in {time.time() - started:.0f} s")


if __name__ == "__main__":
    main()
