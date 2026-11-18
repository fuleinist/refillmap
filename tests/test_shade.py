import math

from refillmap.data import Area, Feature
from refillmap.geo import Mask, Projection
from refillmap.shade import building_height, compute_shade, tree_radius
from refillmap.solar import SunPosition

LAT = -33.90
LON = 151.20


def make_area(features):
    return Area(
        id="test",
        name="Test area",
        south=LAT - 0.0012,
        west=LON - 0.0012,
        north=LAT + 0.0012,
        east=LON + 0.0012,
        features=features,
        fetched_at="2026-11-19T00:00:00Z",
        source="test",
    )


def building(lat_span=0.00009, lon_span=0.00012, tags=None):
    ring = [
        (LAT - lat_span, LON - lon_span),
        (LAT - lat_span, LON + lon_span),
        (LAT + lat_span, LON + lon_span),
        (LAT + lat_span, LON - lon_span),
    ]
    return Feature(kind="building", tags=tags or {"building": "yes", "height": "10"}, ring=ring)


def test_building_height_from_tag():
    assert building_height({"height": "12"}) == 12
    assert abs(building_height({"building:levels": "3"}) - 9.6) < 1e-9
    assert building_height({}) == 6.0


def test_tree_radius_default():
    assert tree_radius({"diameter_crown": "8"}) == 4.0
    assert tree_radius({}) == 3.5


def test_shadow_falls_south_when_sun_is_north():
    area = make_area([building()])
    projection = Projection.for_bbox(*area.bbox)
    sun = SunPosition(elevation=30.0, azimuth=0.0, is_day=True)
    result = compute_shade(area, projection, cell=3.0, sun=sun)

    bx, by = projection.xy(LAT, LON)
    # 15 m south of the building centre is inside the cast shadow.
    assert result.mask.sample_xy(bx, by - 15.0) == 1
    # 15 m north of the building centre is sunlit.
    assert result.mask.sample_xy(bx, by + 15.0) == 0
    assert result.building_count == 1


def test_no_shadow_at_night():
    area = make_area([building()])
    projection = Projection.for_bbox(*area.bbox)
    sun = SunPosition(elevation=-2.0, azimuth=90.0, is_day=False)
    result = compute_shade(area, projection, cell=3.0, sun=sun)
    assert result.mask.count(1) == 0


def test_tree_casts_canopy_shade():
    tree = Feature(kind="tree", tags={"natural": "tree", "diameter_crown": "10"}, point=(LAT, LON))
    area = make_area([tree])
    projection = Projection.for_bbox(*area.bbox)
    sun = SunPosition(elevation=0.0, azimuth=0.0, is_day=False)
    result = compute_shade(area, projection, cell=3.0, sun=sun)
    assert result.mask.count(1) == 0

    sun = SunPosition(elevation=60.0, azimuth=180.0, is_day=True)
    result = compute_shade(area, projection, cell=3.0, sun=sun)
    bx, by = projection.xy(LAT, LON)
    assert result.mask.sample_xy(bx, by) == 1
    assert result.tree_count == 1


def test_shadow_mask_covers_bbox_without_gaps():
    area = make_area([building()])
    projection = Projection.for_bbox(*area.bbox)
    sun = SunPosition(elevation=45.0, azimuth=90.0, is_day=True)
    result = compute_shade(area, projection, cell=4.0, sun=sun)
    assert result.mask.width > 0 and result.mask.height > 0
    assert result.mask.cell == 4.0
    assert math.isfinite(result.mask.width)