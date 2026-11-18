"""Shade model: sun position, building heights and tree crowns."""

from __future__ import annotations

import math
from dataclasses import dataclass

from .data import Area, Feature
from .geo import Mask, Projection, convex_hull, polygon_centroid
from .solar import SunPosition, shadow_vector

DEFAULT_BUILDING_HEIGHT = 6.0
LEVEL_HEIGHT = 3.2
DEFAULT_TREE_HEIGHT = 8.0
DEFAULT_CROWN_RADIUS = 3.5


def _number(value: object) -> float | None:
    if value is None:
        return None
    text = str(value).strip().lower().replace("m", "").strip()
    try:
        return float(text)
    except ValueError:
        return None


def building_height(tags: dict) -> float:
    height = _number(tags.get("height"))
    if height and height > 0:
        return min(max(height, 3.0), 150.0)
    levels = _number(tags.get("building:levels"))
    if levels and levels > 0:
        return min(max(levels * LEVEL_HEIGHT, 3.0), 150.0)
    return DEFAULT_BUILDING_HEIGHT


def tree_height(tags: dict) -> float:
    height = _number(tags.get("height"))
    if height and height > 0:
        return min(max(height, 3.0), 40.0)
    return DEFAULT_TREE_HEIGHT


def tree_radius(tags: dict) -> float:
    diameter = _number(tags.get("diameter_crown"))
    if diameter and diameter > 0:
        return min(max(diameter / 2.0, 1.0), 15.0)
    return DEFAULT_CROWN_RADIUS


@dataclass
class ShadeResult:
    mask: Mask
    sun: SunPosition
    building_count: int
    tree_count: int


def _shadow_polygon(
    ring: list[tuple[float, float]], offset: tuple[float, float], cell: float
) -> list[tuple[float, float]]:
    dx, dy = offset
    moved = [(x + dx, y + dy) for x, y in ring]
    if math.hypot(dx, dy) < cell * 0.5:
        return ring
    return convex_hull(ring + moved)


def compute_shade(
    area: Area,
    projection: Projection,
    cell: float = 3.0,
    sun: SunPosition | None = None,
) -> ShadeResult:
    """Build a 1 = shaded, 0 = sunlit mask for the area bounding box."""
    width = max(1, int(math.ceil((area.east - area.west) * 111_320.0 * math.cos(math.radians(area.south)) / cell)))
    height = max(1, int(math.ceil((area.north - area.south) * 110_540.0 / cell)))
    x0, y0 = projection.xy(area.south, area.west)
    mask = Mask(width, height, cell, x0, y0)

    if sun is None:
        sun = SunPosition(elevation=0.0, azimuth=0.0, is_day=False)

    buildings = area.of_kind("building")
    trees = area.of_kind("tree", "tree_row")

    if not sun.is_day:
        return ShadeResult(mask=mask, sun=sun, building_count=len(buildings), tree_count=len(trees))

    tree_points: list[tuple[float, float, float]] = []
    for feature in trees:
        if feature.kind == "tree" and feature.point:
            lat, lon = feature.point
            tree_points.append((*projection.xy(lat, lon), tree_radius(feature.tags)))
        elif feature.kind == "tree_row" and len(feature.ring) >= 2:
            points = feature.ring
            for index in range(len(points) - 1):
                lat1, lon1 = points[index]
                lat2, lon2 = points[index + 1]
                x1, y1 = projection.xy(lat1, lon1)
                x2, y2 = projection.xy(lat2, lon2)
                length = math.hypot(x2 - x1, y2 - y1)
                steps = max(1, int(length / 6.0))
                for step in range(steps + 1):
                    t = step / steps
                    tree_points.append((x1 + (x2 - x1) * t, y1 + (y2 - y1) * t, 3.0))

    for feature in buildings:
        if len(feature.ring) < 3:
            continue
        ring = [projection.xy(lat, lon) for lat, lon in feature.ring]
        height = building_height(feature.tags)
        offset = shadow_vector(sun, height)
        mask.fill_polygon(ring, 1)
        if offset != (0.0, 0.0):
            mask.fill_polygon(_shadow_polygon(ring, offset, cell), 1)

    for x, y, radius in tree_points:
        offset = shadow_vector(sun, DEFAULT_TREE_HEIGHT)
        mask.fill_circle(x, y, radius, 1)
        if offset != (0.0, 0.0):
            mask.fill_circle(x + offset[0], y + offset[1], radius, 1)
            mask.stroke(x, y, x + offset[0], y + offset[1], radius, 1)

    return ShadeResult(mask=mask, sun=sun, building_count=len(buildings), tree_count=len(tree_points))


def park_shade_fraction(
    feature: Feature, projection: Projection, mask: Mask, max_samples: int = 400
) -> float:
    if len(feature.ring) < 3:
        return 0.0
    ring = [projection.xy(lat, lon) for lat, lon in feature.ring]
    cx, cy = polygon_centroid(ring)
    xs = [p[0] for p in ring]
    ys = [p[1] for p in ring]
    step = max(4.0, math.sqrt(max(1.0, (max(xs) - min(xs)) * (max(ys) - min(ys))) / max_samples))
    shaded = total = 0
    y = min(ys) + step / 2.0
    from .geo import point_in_polygon

    while y < max(ys):
        x = min(xs) + step / 2.0
        while x < max(xs):
            if point_in_polygon(x, y, ring):
                total += 1
                if mask.sample_xy(x, y):
                    shaded += 1
            x += step
        y += step
    if total == 0:
        return 0.0
    return shaded / total