from refillmap.data import Area, Feature
from refillmap.geo import Projection
from refillmap.shade import compute_shade
from refillmap.solar import SunPosition
from refillmap.spots import cool_spots, seat_spots, water_spots

LAT = -33.90
LON = 151.20


def make_area(features):
    return Area(
        id="spots",
        name="Spots",
        south=LAT - 0.001,
        west=LON - 0.001,
        north=LAT + 0.001,
        east=LON + 0.001,
        features=features,
        fetched_at="2026-11-19T00:00:00Z",
        source="test",
    )


def test_water_spots_collect_fountains():
    area = make_area(
        [
            Feature(kind="fountain", tags={"amenity": "drinking_water", "name": "Town fountain"}, point=(LAT, LON)),
            Feature(kind="fountain", tags={"amenity": "drinking_water", "access": "private"}, point=(LAT, LON + 0.0001)),
        ]
    )
    spots = water_spots(area)
    assert len(spots) == 2
    assert spots[0].name == "Town fountain"
    assert "Restricted" in spots[1].note


def test_seat_spots_use_a_default_name():
    area = make_area([Feature(kind="bench", tags={"amenity": "bench"}, point=(LAT, LON))])
    spots = seat_spots(area)
    assert len(spots) == 1
    assert spots[0].name == "Public bench"


def test_cool_spots_include_library_and_park():
    park = Feature(
        kind="park",
        tags={"leisure": "park", "name": "Pocket park"},
        ring=[
            (LAT - 0.0004, LON - 0.0006),
            (LAT - 0.0004, LON + 0.0006),
            (LAT + 0.0004, LON + 0.0006),
            (LAT + 0.0004, LON - 0.0006),
        ],
    )
    library = Feature(kind="library", tags={"amenity": "library", "name": "Branch library"}, point=(LAT, LON))
    area = make_area([park, library])
    projection = Projection.for_bbox(*area.bbox)
    sun = SunPosition(elevation=0.0, azimuth=0.0, is_day=False)
    shade = compute_shade(area, projection, cell=4.0, sun=sun).mask
    spots = cool_spots(area, projection, shade)
    names = [spot.name for spot in spots]
    assert "Pocket park" in names
    assert "Branch library" in names
    library_spot = next(spot for spot in spots if spot.name == "Branch library")
    assert library_spot.indoor


def test_tiny_parks_are_skipped():
    tiny = Feature(
        kind="park",
        tags={"leisure": "park"},
        ring=[
            (LAT - 0.00002, LON - 0.00002),
            (LAT - 0.00002, LON + 0.00002),
            (LAT + 0.00002, LON + 0.00002),
            (LAT + 0.00002, LON - 0.00002),
        ],
    )
    area = make_area([tiny])
    projection = Projection.for_bbox(*area.bbox)
    shade = compute_shade(area, projection, cell=4.0, sun=SunPosition(0.0, 0.0, False)).mask
    assert cool_spots(area, projection, shade) == []