"""Small geometry helpers for refillmap. Standard library only."""

from __future__ import annotations

import math
from dataclasses import dataclass

M_PER_DEG_LAT = 110_540.0


def clamp(value: float, low: float, high: float) -> float:
    if value < low:
        return low
    if value > high:
        return high
    return value


@dataclass(frozen=True)
class Projection:
    """Local flat projection. Metres east and north of a reference point."""

    lat0: float
    lon0: float
    m_per_deg_lon: float

    @classmethod
    def for_bbox(cls, south: float, west: float, north: float, east: float) -> "Projection":
        lat0 = (south + north) / 2.0
        lon0 = (west + east) / 2.0
        return cls(lat0, lon0, 111_320.0 * math.cos(math.radians(lat0)))

    def xy(self, lat: float, lon: float) -> tuple[float, float]:
        return ((lon - self.lon0) * self.m_per_deg_lon, (lat - self.lat0) * M_PER_DEG_LAT)

    def latlon(self, x: float, y: float) -> tuple[float, float]:
        return (self.lat0 + y / M_PER_DEG_LAT, self.lon0 + x / self.m_per_deg_lon)


def polygon_area(points: list[tuple[float, float]]) -> float:
    """Signed shoelace area in square metres."""
    total = 0.0
    n = len(points)
    for i in range(n):
        x1, y1 = points[i]
        x2, y2 = points[(i + 1) % n]
        total += x1 * y2 - x2 * y1
    return total / 2.0


def polygon_centroid(points: list[tuple[float, float]]) -> tuple[float, float]:
    area = polygon_area(points)
    if abs(area) < 1e-9:
        n = max(1, len(points))
        return (sum(p[0] for p in points) / n, sum(p[1] for p in points) / n)
    cx = cy = 0.0
    n = len(points)
    for i in range(n):
        x1, y1 = points[i]
        x2, y2 = points[(i + 1) % n]
        cross = x1 * y2 - x2 * y1
        cx += (x1 + x2) * cross
        cy += (y1 + y2) * cross
    return (cx / (6.0 * area), cy / (6.0 * area))


def point_in_polygon(x: float, y: float, points: list[tuple[float, float]]) -> bool:
    inside = False
    n = len(points)
    j = n - 1
    for i in range(n):
        xi, yi = points[i]
        xj, yj = points[j]
        if (yi > y) != (yj > y):
            span = yj - yi
            if span == 0.0:
                j = i
                continue
            x_cross = (xj - xi) * (y - yi) / span + xi
            if x < x_cross:
                inside = not inside
        j = i
    return inside


def convex_hull(points: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """Andrew monotone chain. Returns points counter-clockwise."""
    pts = sorted(set(points))
    if len(pts) <= 2:
        return pts

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lower: list[tuple[float, float]] = []
    for p in pts:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    upper: list[tuple[float, float]] = []
    for p in reversed(pts):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    return lower[:-1] + upper[:-1]


class Mask:
    """Row-major byte grid over the area bounding box."""

    __slots__ = ("width", "height", "cell", "x0", "y0", "cells")

    def __init__(self, width: int, height: int, cell: float, x0: float = 0.0, y0: float = 0.0):
        self.width = max(1, int(width))
        self.height = max(1, int(height))
        self.cell = float(cell)
        self.x0 = float(x0)
        self.y0 = float(y0)
        self.cells = bytearray(self.width * self.height)

    def index(self, i: int, j: int) -> int:
        return j * self.width + i

    def get(self, i: int, j: int) -> int:
        if i < 0 or j < 0 or i >= self.width or j >= self.height:
            return 0
        return self.cells[j * self.width + i]

    def set(self, i: int, j: int, value: int) -> None:
        if 0 <= i < self.width and 0 <= j < self.height:
            self.cells[j * self.width + i] = value

    def sample_xy(self, x: float, y: float) -> int:
        i = int((x - self.x0) / self.cell)
        j = int((y - self.y0) / self.cell)
        return self.get(i, j)

    def count(self, value: int = 1) -> int:
        return self.cells.count(value)

    def fill_polygon(self, points: list[tuple[float, float]], value: int = 1) -> None:
        if len(points) < 3:
            return
        ys = [p[1] for p in points]
        j0 = max(0, int(math.floor((min(ys) - self.y0) / self.cell)))
        j1 = min(self.height - 1, int(math.floor((max(ys) - self.y0) / self.cell)))
        n = len(points)
        for j in range(j0, j1 + 1):
            yc = self.y0 + (j + 0.5) * self.cell
            xs: list[float] = []
            for k in range(n):
                x1, y1 = points[k]
                x2, y2 = points[(k + 1) % n]
                if (y1 <= yc < y2) or (y2 <= yc < y1):
                    t = (yc - y1) / (y2 - y1)
                    xs.append(x1 + t * (x2 - x1))
            if len(xs) < 2:
                continue
            xs.sort()
            row = j * self.width
            for pair in range(0, len(xs) - 1, 2):
                a, b = xs[pair], xs[pair + 1]
                i0 = max(0, int(math.floor((a - self.x0) / self.cell)))
                i1 = min(self.width - 1, int(math.floor((b - self.x0) / self.cell - 1e-9)))
                for i in range(i0, i1 + 1):
                    self.cells[row + i] = value

    def fill_circle(self, cx: float, cy: float, radius: float, value: int = 1) -> None:
        if radius <= 0:
            return
        i0 = max(0, int(math.floor((cx - radius - self.x0) / self.cell)))
        i1 = min(self.width - 1, int(math.floor((cx + radius - self.x0) / self.cell)))
        j0 = max(0, int(math.floor((cy - radius - self.y0) / self.cell)))
        j1 = min(self.height - 1, int(math.floor((cy + radius - self.y0) / self.cell)))
        r2 = radius * radius
        for j in range(j0, j1 + 1):
            yc = self.y0 + (j + 0.5) * self.cell - cy
            row = j * self.width
            for i in range(i0, i1 + 1):
                xc = self.x0 + (i + 0.5) * self.cell - cx
                if xc * xc + yc * yc <= r2:
                    self.cells[row + i] = value

    def stroke(self, x1: float, y1: float, x2: float, y2: float, radius: float, value: int = 1) -> None:
        dx = x2 - x1
        dy = y2 - y1
        length = math.hypot(dx, dy)
        step = max(self.cell * 0.5, 1e-6)
        n = max(1, int(math.ceil(length / step)))
        for k in range(n + 1):
            t = k / n
            self.fill_circle(x1 + dx * t, y1 + dy * t, radius, value)


def simplify_path(points: list[tuple[float, float]], epsilon: float) -> list[tuple[float, float]]:
    """Ramer-Douglas-Peucker on projected points."""
    if len(points) < 3:
        return list(points)
    start, end = points[0], points[-1]
    dx, dy = end[0] - start[0], end[1] - start[1]
    norm = math.hypot(dx, dy)
    worst = 0.0
    index = 0
    for i in range(1, len(points) - 1):
        px, py = points[i]
        if norm == 0.0:
            dist = math.hypot(px - start[0], py - start[1])
        else:
            dist = abs(dy * (px - start[0]) - dx * (py - start[1])) / norm
        if dist > worst:
            worst = dist
            index = i
    if worst <= epsilon:
        return [start, end]
    left = simplify_path(points[: index + 1], epsilon)
    right = simplify_path(points[index:], epsilon)
    return left[:-1] + right