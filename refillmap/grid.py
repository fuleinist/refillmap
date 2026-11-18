"""Walkable grid and shade-aware routing."""

from __future__ import annotations

import heapq
import math
from array import array
from dataclasses import dataclass

from .data import Area
from .geo import Mask, Projection, simplify_path

WALK_SPEED_MPS = 1.32
PATH_BUFFER_M = 7.0


@dataclass
class Route:
    points: list[tuple[float, float]]  # projected metres
    length_m: float
    shaded_m: float
    cost: float


class WalkGrid:
    """Walkable cells, shade samples and a Dijkstra search from one origin."""

    def __init__(self, area: Area, projection: Projection, shade: Mask, cell: float = 7.0):
        self.area = area
        self.projection = projection
        self.shade = shade
        self.cell = cell
        self.width = max(1, int(math.ceil((area.east - area.west) * 111_320.0 * math.cos(math.radians(area.south)) / cell)))
        self.height = max(1, int(math.ceil((area.north - area.south) * 110_540.0 / cell)))
        self.x0, self.y0 = projection.xy(area.south, area.west)
        self.walkable = Mask(self.width, self.height, cell, self.x0, self.y0)
        self._build()

    def _build(self) -> None:
        for feature in self.area.of_kind("path"):
            if len(feature.ring) < 2:
                continue
            for index in range(len(feature.ring) - 1):
                lat1, lon1 = feature.ring[index]
                lat2, lon2 = feature.ring[index + 1]
                x1, y1 = self.projection.xy(lat1, lon1)
                x2, y2 = self.projection.xy(lat2, lon2)
                self.walkable.stroke(x1, y1, x2, y2, PATH_BUFFER_M, 1)

        for feature in self.area.of_kind("park", "garden"):
            if len(feature.ring) < 3:
                continue
            ring = [self.projection.xy(lat, lon) for lat, lon in feature.ring]
            self.walkable.fill_polygon(ring, 1)

        for feature in self.area.of_kind("building"):
            if len(feature.ring) < 3:
                continue
            ring = [self.projection.xy(lat, lon) for lat, lon in feature.ring]
            self.walkable.fill_polygon(ring, 0)

    def cell_center(self, index: int) -> tuple[float, float]:
        i = index % self.width
        j = index // self.width
        return (self.x0 + (i + 0.5) * self.cell, self.y0 + (j + 0.5) * self.cell)

    def index_of_xy(self, x: float, y: float) -> int | None:
        i = int((x - self.x0) / self.cell)
        j = int((y - self.y0) / self.cell)
        if 0 <= i < self.width and 0 <= j < self.height:
            return j * self.width + i
        return None

    def nearest_walkable(self, x: float, y: float, max_radius_m: float = 60.0) -> int | None:
        index = self.index_of_xy(x, y)
        if index is not None and self.walkable.cells[index]:
            return index
        best: tuple[float, int] | None = None
        radius = self.cell
        while radius <= max_radius_m:
            steps = int(math.ceil(radius / self.cell))
            ci = int((x - self.x0) / self.cell)
            cj = int((y - self.y0) / self.cell)
            for di in range(-steps, steps + 1):
                for dj in range(-steps, steps + 1):
                    if max(abs(di), abs(dj)) != steps:
                        continue
                    i, j = ci + di, cj + dj
                    if 0 <= i < self.width and 0 <= j < self.height:
                        cell_index = j * self.width + i
                        if self.walkable.cells[cell_index]:
                            cx = self.x0 + (i + 0.5) * self.cell
                            cy = self.y0 + (j + 0.5) * self.cell
                            distance = math.hypot(cx - x, cy - y)
                            if best is None or distance < best[0]:
                                best = (distance, cell_index)
            if best is not None:
                return best[1]
            radius += self.cell
        return None

    def search(self, start: int, shade_weight: float = 1.5) -> "SearchResult":
        return SearchResult(self, start, shade_weight)


class SearchResult:
    """Dijkstra result from one origin. Gives cost, distance and path to any cell."""

    NEIGHBOURS = (
        (-1, 0, 1.0),
        (1, 0, 1.0),
        (0, -1, 1.0),
        (0, 1, 1.0),
        (-1, -1, math.sqrt(2)),
        (1, -1, math.sqrt(2)),
        (-1, 1, math.sqrt(2)),
        (1, 1, math.sqrt(2)),
    )

    def __init__(self, grid: WalkGrid, start: int, shade_weight: float = 1.5):
        self.grid = grid
        self.start = start
        self.shade_weight = max(0.0, shade_weight)
        size = grid.width * grid.height
        self.cost = array("d", [math.inf]) * size
        self.distance = array("d", [math.inf]) * size
        self.previous = array("i", [-1]) * size
        self._run()

    def _run(self) -> None:
        grid = self.grid
        width = grid.width
        walkable = grid.walkable.cells
        shade_weight = self.shade_weight
        self.cost[self.start] = 0.0
        self.distance[self.start] = 0.0
        heap = [(0.0, self.start)]
        step = grid.cell
        while heap:
            current_cost, index = heapq.heappop(heap)
            if current_cost > self.cost[index]:
                continue
            i = index % width
            j = index // width
            cx, cy = grid.cell_center(index)
            shaded_here = grid.shade.sample_xy(cx, cy)
            for di, dj, length_factor in self.NEIGHBOURS:
                ni, nj = i + di, j + dj
                if ni < 0 or nj < 0 or ni >= width or nj >= grid.height:
                    continue
                neighbour = nj * width + ni
                if not walkable[neighbour]:
                    continue
                nx, ny = grid.cell_center(neighbour)
                segment = step * length_factor
                exposed = 0 if (shaded_here and grid.shade.sample_xy(nx, ny)) else 1
                new_cost = current_cost + segment * (1.0 + shade_weight * exposed)
                if new_cost < self.cost[neighbour]:
                    self.cost[neighbour] = new_cost
                    self.distance[neighbour] = self.distance[index] + segment
                    self.previous[neighbour] = index
                    heapq.heappush(heap, (new_cost, neighbour))

    def reachable(self, index: int | None) -> bool:
        return index is not None and math.isfinite(self.cost[index])

    def route(self, target: int | None) -> Route | None:
        if not self.reachable(target):
            return None
        points: list[tuple[float, float]] = []
        shaded = 0.0
        total = 0.0
        index = target
        while index is not None and index >= 0:
            points.append(self.grid.cell_center(index))
            previous = self.previous[index]
            if previous < 0:
                break
            px, py = self.grid.cell_center(previous)
            cx, cy = self.grid.cell_center(index)
            segment = math.hypot(cx - px, cy - py)
            total += segment
            if self.grid.shade.sample_xy((cx + px) / 2.0, (cy + py) / 2.0):
                shaded += segment
            index = previous
        points.reverse()
        simplified = simplify_path(points, max(1.5, self.grid.cell * 0.45))
        return Route(
            points=simplified,
            length_m=self.distance[target] if math.isfinite(self.distance[target]) else total,
            shaded_m=shaded,
            cost=self.cost[target],
        )