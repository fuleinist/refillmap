"""Area data: bundled OpenStreetMap snapshots and the live Overpass fetch."""

from __future__ import annotations

import json
import math
import os
import sqlite3
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Iterable
from urllib.error import URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

OVERPASS_URL = "https://overpass-api.de/api/interpreter"
SNAPSHOT_TTL_SECONDS = 7 * 24 * 3600
USER_AGENT = "refillmap/0.1 (github.com/fuleinist/refillmap)"


@dataclass
class Feature:
    kind: str
    tags: dict
    point: tuple[float, float] | None = None
    ring: list[tuple[float, float]] = field(default_factory=list)

    @property
    def is_area(self) -> bool:
        return len(self.ring) >= 3


@dataclass
class Area:
    id: str
    name: str
    south: float
    west: float
    north: float
    east: float
    features: list[Feature]
    fetched_at: str
    source: str

    @property
    def bbox(self) -> tuple[float, float, float, float]:
        return (self.south, self.west, self.north, self.east)

    def of_kind(self, *kinds: str) -> list[Feature]:
        wanted = set(kinds)
        return [f for f in self.features if f.kind in wanted]


KEEP_TAGS = {
    "building": ("building", "height", "building:levels", "name"),
    "tree": ("natural", "height", "diameter_crown", "species", "genus"),
    "tree_row": ("natural",),
    "park": ("leisure", "name"),
    "garden": ("leisure", "name"),
    "fountain": ("amenity", "name", "access", "wheelchair", "drinking_water", "fee"),
    "bench": ("amenity", "name", "backrest", "material", "access"),
    "library": ("amenity", "name", "opening_hours", "wheelchair"),
    "shelter": ("amenity", "name", "shelter_type"),
    "path": ("highway", "name", "footway", "surface", "access"),
}


def kind_of(tags: dict) -> str | None:
    if tags.get("amenity") == "drinking_water":
        return "fountain"
    if tags.get("amenity") == "bench":
        return "bench"
    if tags.get("amenity") == "library":
        return "library"
    if tags.get("amenity") == "shelter":
        return "shelter"
    if tags.get("leisure") == "park":
        return "park"
    if tags.get("leisure") == "garden":
        return "garden"
    if tags.get("natural") == "tree":
        return "tree"
    if tags.get("natural") == "tree_row":
        return "tree_row"
    if tags.get("building"):
        return "building"
    if tags.get("highway"):
        return "path"
    return None


def _round(value: float) -> float:
    return round(float(value), 6)


def slimmable(feature: dict) -> dict:
    out = {"k": feature["k"]}
    if "at" in feature:
        out["at"] = [_round(feature["at"][0]), _round(feature["at"][1])]
    else:
        out["path"] = [[_round(p[0]), _round(p[1])] for p in feature["path"]]
    if feature.get("t"):
        out["t"] = feature["t"]
    return out


def parse_snapshot(payload: dict) -> tuple[list[Feature], str]:
    """Parse the slim snapshot format into features."""
    features: list[Feature] = []
    for raw in payload.get("features", []):
        kind = raw["k"]
        tags = raw.get("t") or {}
        if "at" in raw:
            features.append(Feature(kind=kind, tags=tags, point=(float(raw["at"][0]), float(raw["at"][1]))))
        else:
            ring = [(float(p[0]), float(p[1])) for p in raw["path"]]
            features.append(Feature(kind=kind, tags=tags, ring=ring))
    return features, payload.get("fetchedAt", "")


def slim_from_osm(osm: dict) -> list[dict]:
    """Convert a raw Overpass JSON payload into the slim snapshot format."""
    features: list[dict] = []
    for element in osm.get("elements", []):
        tags = element.get("tags") or {}
        kind = kind_of(tags)
        if not kind:
            continue
        keep = {key: tags[key] for key in KEEP_TAGS.get(kind, ()) if key in tags}
        if kind == "tree":
            if element.get("type") != "node" or element.get("lat") is None:
                continue
            features.append({"k": "tree", "at": [element["lat"], element["lon"]], "t": keep})
            continue
        geometry = element.get("geometry") or []
        points = [[p["lat"], p["lon"]] for p in geometry if p and p.get("lat") is not None]
        if not points:
            continue
        if kind in ("fountain", "bench", "library", "shelter"):
            lat = sum(p[0] for p in points) / len(points)
            lon = sum(p[1] for p in points) / len(points)
            features.append({"k": kind, "at": [lat, lon], "t": keep})
        elif len(points) >= 2:
            features.append({"k": kind, "path": points, "t": keep})
    return features


def overpass_query(south: float, west: float, north: float, east: float) -> str:
    box = f"{south},{west},{north},{east}"
    return (
        "[out:json][timeout:90];\n(\n"
        f'  node["amenity"="drinking_water"]({box});\n'
        f'  way["amenity"="drinking_water"]({box});\n'
        f'  node["amenity"="bench"]({box});\n'
        f'  way["amenity"="bench"]({box});\n'
        f'  way["leisure"="park"]({box});\n'
        f'  way["leisure"="garden"]({box});\n'
        f'  node["natural"="tree"]({box});\n'
        f'  way["natural"="tree_row"]({box});\n'
        f'  way["building"]({box});\n'
        f'  way["highway"~"^(footway|path|pedestrian|steps|residential|living_street|service|unclassified|tertiary|secondary|primary)$"]({box});\n'
        f'  node["amenity"="library"]({box});\n'
        f'  way["amenity"="library"]({box});\n'
        f'  node["amenity"="shelter"]({box});\n'
        ");\nout geom;"
    )


class SnapshotCache:
    """SQLite cache for live Overpass payloads."""

    def __init__(self, path: str):
        self.path = path
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.execute(
            "CREATE TABLE IF NOT EXISTS snapshots (key TEXT PRIMARY KEY, created_at REAL, payload TEXT)"
        )
        self.conn.commit()

    def get(self, key: str, ttl_seconds: float = SNAPSHOT_TTL_SECONDS) -> dict | None:
        row = self.conn.execute("SELECT created_at, payload FROM snapshots WHERE key = ?", (key,)).fetchone()
        if not row:
            return None
        created_at, payload = row
        if time.time() - created_at > ttl_seconds:
            return None
        return json.loads(payload)

    def put(self, key: str, payload: dict) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO snapshots (key, created_at, payload) VALUES (?, ?, ?)",
            (key, time.time(), json.dumps(payload, separators=(",", ":"))),
        )
        self.conn.commit()


def fetch_overpass(south: float, west: float, north: float, east: float, timeout: float = 90.0) -> dict:
    body = urlencode({"data": overpass_query(south, west, north, east)}).encode("utf-8")
    request = Request(
        OVERPASS_URL,
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded", "User-Agent": USER_AGENT},
    )
    with urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def live_area(
    south: float,
    west: float,
    north: float,
    east: float,
    cache: SnapshotCache | None = None,
    name: str = "Custom location",
    timeout: float = 90.0,
) -> Area:
    """Fetch a bbox from Overpass. Raise RuntimeError when the fetch fails."""
    key = f"{south:.4f},{west:.4f},{north:.4f},{east:.4f}"
    payload = cache.get(key) if cache else None
    if payload is None:
        try:
            osm = fetch_overpass(south, west, north, east, timeout=timeout)
        except (URLError, TimeoutError, OSError, ValueError) as exc:
            raise RuntimeError(f"Overpass fetch failed: {exc}") from exc
        payload = {
            "v": 1,
            "name": name,
            "bbox": {"south": south, "west": west, "north": north, "east": east},
            "fetchedAt": datetime.now(timezone.utc).isoformat(),
            "source": "OpenStreetMap via Overpass API (ODbL)",
            "features": slim_from_osm(osm),
        }
        if cache:
            cache.put(key, payload)
    features, fetched_at = parse_snapshot(payload)
    return Area(
        id="live",
        name=name,
        south=south,
        west=west,
        north=north,
        east=east,
        features=features,
        fetched_at=fetched_at,
        source=payload.get("source", "OpenStreetMap via Overpass API (ODbL)"),
    )


def load_area_file(path: str, area_id: str | None = None) -> Area:
    with open(path, "r", encoding="utf-8") as handle:
        payload = json.load(handle)
    bbox = payload.get("bbox") or {}
    features, fetched_at = parse_snapshot(payload)
    south = float(bbox["south"])
    west = float(bbox["west"])
    north = float(bbox["north"])
    east = float(bbox["east"])
    return Area(
        id=area_id or payload.get("name", os.path.basename(path)),
        name=payload.get("name", area_id or "Area"),
        south=south,
        west=west,
        north=north,
        east=east,
        features=features,
        fetched_at=fetched_at,
        source=payload.get("source", "OpenStreetMap (ODbL)"),
    )


def bbox_around(lat: float, lon: float, radius_m: float) -> tuple[float, float, float, float]:
    d_lat = radius_m / 110_540.0
    d_lon = radius_m / (111_320.0 * max(0.05, math.cos(math.radians(lat))))
    return (lat - d_lat, lon - d_lon, lat + d_lat, lon + d_lon)