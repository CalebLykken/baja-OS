"""Build the offline street-address index (addresses.sqlite) for search,
from the OpenStreetMap extract that install-routing.sh downloads.

Run with the tools environment that has pyosmium (install-routing.sh sets
it up and runs this):

    venv/bin/python build_addresses.py washington-latest.osm.pbf MAPS_DIR

Only addresses inside the installed map's area (MAPS_DIR/region.json) are
kept. Each row is "house number, street, city" with a position: the node
itself, or the middle of a building outline.
"""

import json
import sqlite3
import sys
import time
from pathlib import Path

import osmium

INDEX_NAME = "addresses.sqlite"


class Addresses(osmium.SimpleHandler):
    def __init__(self, bbox):
        super().__init__()
        self.w, self.s, self.e, self.n = bbox
        self.rows = {}

    def _keep(self, tags, lon, lat):
        if not (self.w <= lon <= self.e and self.s <= lat <= self.n):
            return
        number, street = tags.get("addr:housenumber"), tags.get("addr:street")
        if not number or not street:
            return
        city = tags.get("addr:city", "")
        key = (number.strip(), street.strip(), city)
        if key not in self.rows:
            self.rows[key] = (tags.get("addr:postcode", ""), lon, lat)

    def node(self, n):
        if "addr:housenumber" in n.tags and n.location.valid():
            self._keep(n.tags, n.location.lon, n.location.lat)

    def way(self, w):
        if "addr:housenumber" not in w.tags:
            return
        try:
            pts = [(nd.lon, nd.lat) for nd in w.nodes if nd.location.valid()]
        except osmium.InvalidLocationError:
            return
        if pts:
            self._keep(w.tags, sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts))


def main():
    pbf, maps_dir = sys.argv[1], Path(sys.argv[2]).expanduser()
    region = json.loads((maps_dir / "region.json").read_text())
    started = time.time()
    h = Addresses(region["bbox"])
    # Building outlines need their nodes' positions; keep them in memory.
    h.apply_file(pbf, locations=True, idx="flex_mem")

    tmp = maps_dir / (INDEX_NAME + ".tmp")
    tmp.unlink(missing_ok=True)
    db = sqlite3.connect(tmp)
    db.execute("CREATE VIRTUAL TABLE addresses USING fts5(number, street, city, postcode UNINDEXED,"
               " lon UNINDEXED, lat UNINDEXED, tokenize='unicode61 remove_diacritics 2')")
    db.executemany("INSERT INTO addresses VALUES (?, ?, ?, ?, ?, ?)",
                   [(num, street, city, post, lon, lat)
                    for (num, street, city), (post, lon, lat) in h.rows.items()])
    db.commit()
    db.execute("INSERT INTO addresses(addresses) VALUES('optimize')")
    db.commit()
    db.close()
    tmp.replace(maps_dir / INDEX_NAME)
    print(f"Indexed {len(h.rows)} addresses in {time.time() - started:.0f} s")


if __name__ == "__main__":
    main()
