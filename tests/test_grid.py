import math

from refillmap.data import Area, Feature
from refillmap.geo import Mask, Projection
from refillmap.grid import WalkGrid

LAT = -33.90
LON = 151.20
SPAN = 0.0018  # about 200 m each way


def make_area(paths, extras=None):
    features = [
        Feature(kind="path", tags={"highway": "footway"}, ring=[(LAT + dy, LON + dx) for dx, dy in path])
        for path in paths
    ]
    features.extend(extras or [])
    return Area(
        id="grid-test",
        name="Grid test",
        south=LAT - SPAN,
        west=LON - SPAN,
        north=LAT + SPAN,
        east=LON + SPAN,
        features=features,
        fetched_at="2026-11-19T00:00:00Z",
        source="test",
    )


def shade_mask_for(area, projection, shaded_lines):
    mask = Mask(
        width=int(math.ceil((area.east - area.west) * 111_320 * math.cos(math.radians(area.south)) / 4.0)),
        height=int(math.ceil((area.north - area.south) * 110_540 / 4.0)),
        cell=4.0,
        x0=projection.xy(area.south, area.west)[0],
        y0=projection.xy(area.south, area.west)[1],
    )
    for line in shaded_lines:
        points = [projection.xy(LAT + dy, LON + dx) for dx, dy in line]
        for index in range(len(points) - 1):
            x1, y1 = points[index]
            x2, y2 = points[index + 1]
            mask.stroke(x1, y1, x2, y2, 6.0, 1)
    return mask


def test_route_prefers_the_shaded_branch():
    # Two equal length branches between the same endpoints. Only the north branch has shade.
    branch_north = [(-0.0009, 0.0), (0.0, 0.0006), (0.0009, 0.0)]
    branch_south = [(-0.0009, 0.0), (0.0, -0.0006), (0.0009, 0.0)]
    area = make_area([branch_north, branch_south])
    projection = Projection.for_bbox(*area.bbox)
    shade = shade_mask_for(area, projection, [branch_north])
    grid = WalkGrid(area, projection, shade, cell=7.0)

    start = grid.nearest_walkable(*projection.xy(LAT, LON - 0.0009), 30.0)
    target = grid.nearest_walkable(*projection.xy(LAT, LON + 0.0009), 30.0)
    assert start is not None and target is not None

    shaded_route = grid.search(start, shade_weight=4.0).route(target)
    assert shaded_route is not None
    assert shaded_route.length_m > 0
    share = shaded_route.shaded_m / shaded_route.length_m
    assert share > 0.55

    open_route = grid.search(start, shade_weight=0.0).route(target)
    assert open_route is not None
    assert math.isfinite(open_route.cost)


def test_route_without_shade_preference_is_short():
    branch_north = [(-0.0009, 0.0), (0.0, 0.0006), (0.0009, 0.0)]
    branch_south = [(-0.0009, 0.0), (0.0, -0.0006), (0.0009, 0.0)]
    area = make_area([branch_north, branch_south])
    projection = Projection.for_bbox(*area.bbox)
    shade = shade_mask_for(area, projection, [branch_north])
    grid = WalkGrid(area, projection, shade, cell=7.0)

    start = grid.nearest_walkable(*projection.xy(LAT, LON - 0.0009), 30.0)
    target = grid.nearest_walkable(*projection.xy(LAT, LON + 0.0009), 30.0)
    route = grid.search(start, shade_weight=0.0).route(target)
    straight = 2 * math.hypot(0.0009 * 111_320 * math.cos(math.radians(LAT)), 0.0006 * 110_540)
    assert abs(route.length_m - straight) < straight * 0.35


def test_grid_blocks_buildings():
    area = make_area(
        [[(-0.0009, 0.0), (0.0009, 0.0)]],
        extras=[
            Feature(
                kind="building",
                tags={"building": "yes"},
                ring=[
                    (LAT - 0.00004, LON - 0.00005),
                    (LAT - 0.00004, LON + 0.00005),
                    (LAT + 0.00004, LON + 0.00005),
                    (LAT + 0.00004, LON - 0.00005),
                ],
            )
        ],
    )
    projection = Projection.for_bbox(*area.bbox)
    shade = Mask(10, 10, 4.0)
    grid = WalkGrid(area, projection, shade, cell=7.0)
    x, y = projection.xy(LAT, LON)
    index = grid.index_of_xy(x, y)
    assert index is not None
    assert grid.walkable.cells[index] == 0


def test_unreachable_target_returns_no_route():
    area = make_area([[(-0.0009, 0.0), (-0.0004, 0.0)]])
    projection = Projection.for_bbox(*area.bbox)
    shade = Mask(10, 10, 4.0)
    grid = WalkGrid(area, projection, shade, cell=7.0)
    start = grid.nearest_walkable(*projection.xy(LAT, LON - 0.0008), 30.0)
    far = grid.nearest_walkable(*projection.xy(LAT, LON + 0.0015), 30.0)
    assert start is not None
    assert far is None or grid.search(start, 0.0).route(far) is None