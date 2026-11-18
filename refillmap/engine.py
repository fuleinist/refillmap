"""Plan engine: area cache, sun, shade, routing and response shaping."""

from __future__ import annotations

import math
import os
import threading
from dataclasses import dataclass
from datetime import datetime, timezone

from .data import Area, SnapshotCache, load_area_file, bbox_around, live_area
from .geo import Mask, Projection
from .grid import WALK_SPEED_MPS, SearchResult, WalkGrid
from .shade import ShadeResult, compute_shade
from .solar import SunPosition, solar_position
from .spots import Spot, cool_spots, seat_spots, water_spots
from .weather import Weather, WeatherCache, best_windows, comfort_band, load_weather

MAX_ORIGIN_SNAP_M = 120.0


@dataclass
class Prepared:
    area: Area
    projection: Projection
    map_payload: dict
    shade_cache: dict[str, ShadeResult]
    grid: WalkGrid | None = None


def _round_coord(value: float) -> float:
    return round(value, 5)


def _ring_latlon(feature, projection: Projection) -> list[list[float]]:
    return [[_round_coord(lat), _round_coord(lon)] for lat, lon in feature.ring]


def build_map_payload(area: Area, projection: Projection) -> dict:
    buildings = []
    for feature in area.of_kind("building"):
        if len(feature.ring) >= 3:
            buildings.append(_ring_latlon(feature, projection))
    parks = []
    for feature in area.of_kind("park", "garden"):
        if len(feature.ring) >= 3:
            parks.append(
                {
                    "ring": _ring_latlon(feature, projection),
                    "name": feature.tags.get("name", ""),
                    "kind": feature.kind,
                }
            )
    paths = []
    for feature in area.of_kind("path"):
        if len(feature.ring) >= 2:
            paths.append(_ring_latlon(feature, projection))
    trees = []
    for feature in area.of_kind("tree"):
        if feature.point:
            from .shade import tree_radius

            trees.append(
                [
                    _round_coord(feature.point[0]),
                    _round_coord(feature.point[1]),
                    round(tree_radius(feature.tags), 1),
                ]
            )
    return {
        "bbox": {"south": area.south, "west": area.west, "north": area.north, "east": area.east},
        "buildings": buildings,
        "parks": parks,
        "paths": paths,
        "trees": trees,
    }


def _shadow_bitmap(shade: ShadeResult) -> dict:
    import base64

    mask = shade.mask
    row_bytes = (mask.width + 7) // 8
    buffer = bytearray(row_bytes * mask.height)
    for j in range(mask.height):
        row = j * mask.width
        out = j * row_bytes
        for i in range(mask.width):
            if mask.cells[row + i]:
                buffer[out + (i >> 3)] |= 0x80 >> (i & 7)
    return {
        "width": mask.width,
        "height": mask.height,
        "cell": mask.cell,
        "bits": base64.b64encode(bytes(buffer)).decode("ascii"),
    }


class Engine:
    """Loads areas, caches derived grids and answers plan requests."""

    def __init__(self, data_dir: str, cache_dir: str, allow_live: bool = True):
        self.data_dir = os.path.abspath(data_dir)
        self.cache_dir = os.path.abspath(cache_dir)
        os.makedirs(self.cache_dir, exist_ok=True)
        self.allow_live = allow_live
        self.snapshot_cache = SnapshotCache(os.path.join(self.cache_dir, "refillmap.sqlite"))
        self.weather_cache = WeatherCache(os.path.join(self.cache_dir, "refillmap.sqlite"))
        self._areas: dict[str, dict] = {}
        self._prepared: dict[str, Prepared] = {}
        self._lock = threading.Lock()
        self._load_index()

    def _load_index(self) -> None:
        import json

        index_path = os.path.join(self.data_dir, "areas.json")
        with open(index_path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
        for entry in payload.get("areas", []):
            self._areas[entry["id"]] = entry

    def list_areas(self) -> list[dict]:
        out = []
        for area_id, entry in self._areas.items():
            out.append({"id": area_id, "name": entry["name"], "note": entry.get("note", "")})
        return out

    def area(self, area_id: str) -> Area:
        entry = self._areas.get(area_id)
        if not entry:
            raise KeyError(area_id)
        path = os.path.join(self.data_dir, entry["file"])
        return load_area_file(path, area_id)

    def live_area_for(self, lat: float, lon: float, radius_m: float = 1200.0) -> Area:
        if not self.allow_live:
            raise RuntimeError("Live Overpass fetch is disabled")
        south, west, north, east = bbox_around(lat, lon, radius_m)
        area = live_area(south, west, north, east, cache=self.snapshot_cache, name="Custom location")
        area.id = "live"
        return area

    def prepared(self, area: Area) -> Prepared:
        key = f"{area.id}:{area.south:.4f},{area.west:.4f},{area.north:.4f},{area.east:.4f}"
        with self._lock:
            prepared = self._prepared.get(key)
            if prepared is None:
                projection = Projection.for_bbox(*area.bbox)
                prepared = Prepared(
                    area=area,
                    projection=projection,
                    map_payload=build_map_payload(area, projection),
                    shade_cache={},
                )
                self._prepared[key] = prepared
            return prepared

    def shade_for(self, prepared: Prepared, sun: SunPosition, cell: float = 3.0) -> ShadeResult:
        key = f"{sun.elevation:.2f}:{sun.azimuth:.2f}"
        cached = prepared.shade_cache.get(key)
        if cached is not None:
            return cached
        result = compute_shade(prepared.area, prepared.projection, cell=cell, sun=sun)
        if len(prepared.shade_cache) > 12:
            prepared.shade_cache.clear()
        prepared.shade_cache[key] = result
        return result

    def plan(
        self,
        area: Area,
        when: datetime,
        shade_weight: float = 1.5,
        origin: tuple[float, float] | None = None,
        include_weather: bool = True,
    ) -> dict:
        prepared = self.prepared(area)
        if when.tzinfo is None:
            when = when.astimezone()
        sun = solar_position(
            (area.south + area.north) / 2.0,
            (area.west + area.east) / 2.0,
            when,
        )
        shade = self.shade_for(prepared, sun)

        if prepared.grid is None:
            prepared.grid = WalkGrid(area, prepared.projection, shade.mask, cell=7.0)
        else:
            prepared.grid.shade = shade.mask
        grid = prepared.grid

        origin_lat, origin_lon = origin or (
            (area.south + area.north) / 2.0,
            (area.west + area.east) / 2.0,
        )
        ox, oy = prepared.projection.xy(origin_lat, origin_lon)
        start_index = grid.nearest_walkable(ox, oy, MAX_ORIGIN_SNAP_M)
        if start_index is None:
            raise RuntimeError("No walkable path near the start point")

        search = grid.search(start_index, shade_weight=shade_weight)

        water = self._pick(search, grid, shade.mask, prepared.projection, water_spots(area), "water")
        seats = self._pick(search, grid, shade.mask, prepared.projection, seat_spots(area), "seat")
        cool = self._pick(search, grid, shade.mask, prepared.projection, cool_spots(area, prepared.projection, shade.mask), "cool")

        weather = self._weather(area, when) if include_weather else None

        return {
            "area": {
                "id": area.id,
                "name": area.name,
                "bbox": {"south": area.south, "west": area.west, "north": area.north, "east": area.east},
                "source": area.source,
                "fetchedAt": area.fetched_at,
            },
            "at": when.isoformat(),
            "origin": {"lat": _round_coord(origin_lat), "lon": _round_coord(origin_lon)},
            "sun": {
                "elevation": round(sun.elevation, 2),
                "azimuth": round(sun.azimuth, 2),
                "isDay": sun.is_day,
            },
            "shade": {
                "cellM": shade.mask.cell,
                "buildings": shade.building_count,
                "trees": shade.tree_count,
                "bitmap": _shadow_bitmap(shade),
            },
            "shadeWeight": round(shade_weight, 2),
            "grid": {"cellM": grid.cell, "width": grid.width, "height": grid.height},
            "weather": weather,
            "targets": {"water": water, "seat": seats, "cool": cool},
            "map": prepared.map_payload,
            "notes": self._notes(area, shade),
        }

    def _weather(self, area: Area, when: datetime) -> dict:
        lat = (area.south + area.north) / 2.0
        lon = (area.west + area.east) / 2.0
        weather: Weather = load_weather(lat, lon, cache=self.weather_cache)
        if not weather.available:
            return {"available": False, "source": weather.source, "reason": weather.reason}
        local_naive = when.astimezone().replace(tzinfo=None)
        current = weather.now(local_naive)
        day = local_naive.date()
        hours = []
        for hour in weather.hourly:
            try:
                stamp = datetime.fromisoformat(hour.time)
            except ValueError:
                continue
            if stamp.date() != day:
                continue
            hours.append(
                {
                    "time": hour.time,
                    "tempC": hour.temp_c,
                    "apparentC": hour.apparent_c,
                    "uvIndex": hour.uv_index,
                    "rainChance": hour.rain_chance,
                    "band": comfort_band(hour.apparent_c),
                }
            )
        return {
            "available": True,
            "source": weather.source,
            "fetchedAt": weather.fetched_at,
            "timezone": weather.timezone,
            "now": {
                "time": current.time if current else None,
                "tempC": current.temp_c if current else None,
                "apparentC": current.apparent_c if current else None,
                "uvIndex": current.uv_index if current else None,
                "humidity": current.humidity if current else None,
                "band": comfort_band(current.apparent_c if current else None),
            },
            "hours": hours,
            "bestWindows": best_windows(weather.hourly, limit=3),
        }

    def _pick(
        self,
        search: SearchResult,
        grid: WalkGrid,
        shade_mask: Mask,
        projection: Projection,
        spots: list[Spot],
        kind: str,
    ) -> dict | None:
        best: tuple[float, Spot, int] | None = None
        for spot in spots:
            x, y = projection.xy(spot.lat, spot.lon)
            index = grid.nearest_walkable(x, y, 45.0)
            if index is None or not search.reachable(index):
                continue
            spot.shaded = bool(shade_mask.sample_xy(x, y))
            shade_value = spot.shade_fraction if kind == "cool" else (1.0 if spot.shaded else 0.0)
            penalty = 1.45 - 0.45 * max(0.0, min(1.0, shade_value))
            if spot.tags.get("access") in ("private", "no"):
                penalty *= 1.6
            score = search.cost[index] * penalty
            if best is None or score < best[0]:
                best = (score, spot, index)
        if best is None:
            return None
        _, spot, index = best
        route = search.route(index)
        if route is None:
            return None
        route_points = [list(projection.latlon(x, y)) for x, y in route.points]
        route_points = [[_round_coord(lat), _round_coord(lon)] for lat, lon in route_points]
        length = route.length_m
        shaded_share = (route.shaded_m / length) if length > 0 else 0.0
        return {
            "spot": {
                "kind": kind,
                "name": spot.name,
                "lat": _round_coord(spot.lat),
                "lon": _round_coord(spot.lon),
                "shaded": spot.shaded,
                "shadePct": round(100.0 * spot.shade_fraction, 0) if kind == "cool" else (100 if spot.shaded else 0),
                "indoor": spot.indoor,
                "note": spot.note,
                "tags": {k: v for k, v in spot.tags.items() if k in ("opening_hours", "wheelchair", "access", "backrest")},
            },
            "route": {
                "points": route_points,
                "lengthM": round(length, 0),
                "minutes": round(length / WALK_SPEED_MPS / 60.0, 1),
                "shadePct": round(100.0 * shaded_share, 0),
                "cost": round(route.cost, 1),
            },
        }

    def _notes(self, area: Area, shade: ShadeResult) -> list[str]:
        notes = [
            "Shade is an estimate from mapped buildings and trees. It is not a site survey.",
            f"Shade grid {shade.mask.cell:.0f} m. Walk grid 7 m.",
            "Mapped data is incomplete. A blank area is unobserved, not safe.",
        ]
        if not shade.sun.is_day:
            notes.append("The sun is below the horizon. Shade values do not apply now.")
        return notes