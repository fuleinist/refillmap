"""Candidate places: drinking water, shaded seats and cool spaces."""

from __future__ import annotations

from dataclasses import dataclass, field

from .data import Area, Feature
from .geo import Projection, polygon_area, polygon_centroid
from .shade import park_shade_fraction
from .geo import Mask

MIN_PARK_AREA_M2 = 600.0


@dataclass
class Spot:
    kind: str  # water | seat | cool
    name: str
    lat: float
    lon: float
    tags: dict = field(default_factory=dict)
    shaded: bool = False
    shade_fraction: float = 0.0
    indoor: bool = False
    note: str = ""


def _label(feature: Feature, fallback: str) -> str:
    name = (feature.tags.get("name") or "").strip()
    return name or fallback


def water_spots(area: Area) -> list[Spot]:
    spots = []
    for feature in area.of_kind("fountain"):
        if not feature.point:
            continue
        lat, lon = feature.point
        note = ""
        if feature.tags.get("drinking_water") == "no":
            note = "Tagged as not for drinking. Check the sign."
        elif feature.tags.get("access") in ("private", "no"):
            note = "Restricted access."
        spots.append(
            Spot(
                kind="water",
                name=_label(feature, "Drinking fountain"),
                lat=lat,
                lon=lon,
                tags=feature.tags,
                note=note,
            )
        )
    return spots


def seat_spots(area: Area) -> list[Spot]:
    spots = []
    for feature in area.of_kind("bench"):
        if not feature.point:
            continue
        lat, lon = feature.point
        note = ""
        if feature.tags.get("access") in ("private", "no"):
            note = "Restricted access."
        spots.append(
            Spot(
                kind="seat",
                name=_label(feature, "Public bench"),
                lat=lat,
                lon=lon,
                tags=feature.tags,
                note=note,
            )
        )
    return spots


def cool_spots(area: Area, projection: Projection, shade: Mask) -> list[Spot]:
    spots: list[Spot] = []
    for feature in area.of_kind("park", "garden"):
        if len(feature.ring) < 3:
            continue
        ring = [projection.xy(lat, lon) for lat, lon in feature.ring]
        if abs(polygon_area(ring)) < MIN_PARK_AREA_M2:
            continue
        cx, cy = polygon_centroid(ring)
        lat, lon = projection.latlon(cx, cy)
        fraction = park_shade_fraction(feature, projection, shade)
        kind_label = "Park" if feature.kind == "park" else "Garden"
        spots.append(
            Spot(
                kind="cool",
                name=_label(feature, kind_label),
                lat=lat,
                lon=lon,
                tags=feature.tags,
                shade_fraction=fraction,
                note=kind_label,
            )
        )

    for feature in area.of_kind("library"):
        if not feature.point:
            continue
        lat, lon = feature.point
        spots.append(
            Spot(
                kind="cool",
                name=_label(feature, "Public library"),
                lat=lat,
                lon=lon,
                tags=feature.tags,
                shaded=True,
                shade_fraction=1.0,
                indoor=True,
                note="Indoor cool refuge",
            )
        )
    return spots