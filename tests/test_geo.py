from refillmap.geo import (
    Mask,
    Projection,
    convex_hull,
    point_in_polygon,
    polygon_area,
    polygon_centroid,
    simplify_path,
)


def test_projection_round_trip():
    projection = Projection.for_bbox(-33.92, 151.16, -33.90, 151.19)
    lat, lon = -33.91, 151.175
    x, y = projection.xy(lat, lon)
    back_lat, back_lon = projection.latlon(x, y)
    assert abs(back_lat - lat) < 1e-9
    assert abs(back_lon - lon) < 1e-9


def test_point_in_polygon_square():
    square = [(0, 0), (10, 0), (10, 10), (0, 10)]
    assert point_in_polygon(5, 5, square)
    assert not point_in_polygon(15, 5, square)
    assert not point_in_polygon(-1, 5, square)


def test_polygon_area_and_centroid():
    square = [(0, 0), (10, 0), (10, 10), (0, 10)]
    assert abs(polygon_area(square) - 100) < 1e-6
    cx, cy = polygon_centroid(square)
    assert abs(cx - 5) < 1e-6
    assert abs(cy - 5) < 1e-6


def test_mask_fills_polygon():
    mask = Mask(10, 10, 1.0)
    mask.fill_polygon([(0, 0), (5, 0), (5, 5), (0, 5)])
    assert 24 <= mask.count(1) <= 26


def test_mask_circle_radius():
    mask = Mask(20, 20, 1.0)
    mask.fill_circle(10, 10, 3.0)
    counted = mask.count(1)
    assert 20 <= counted <= 36


def test_convex_hull_of_square_with_inner_point():
    hull = convex_hull([(0, 0), (10, 0), (10, 10), (0, 10), (5, 5)])
    assert len(hull) == 4
    assert (5, 5) not in hull


def test_simplify_removes_collinear_points():
    points = [(0, 0), (1, 0), (2, 0), (3, 0)]
    simplified = simplify_path(points, 0.5)
    assert simplified == [(0, 0), (3, 0)]


def test_simplify_keeps_corner():
    points = [(0, 0), (5, 0), (5, 5)]
    simplified = simplify_path(points, 0.5)
    assert simplified == [(0, 0), (5, 0), (5, 5)]