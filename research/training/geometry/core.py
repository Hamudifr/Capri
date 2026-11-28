"""Computational geometry: shapes, hulls, and spatial data structures.

Stdlib-only. Pure computation, no external dependencies.

Core primitives:
- Point/vector arithmetic in 2D
- Line and polygon operations (intersection, containment, area)
- Convex hull (Graham scan, monotone chain)
- Voronoi diagram (brute-force)
- k-d tree for nearest-neighbor queries
"""

from __future__ import annotations

import math

Point = tuple[float, float]


# ===========================================================================
# Basic vector operations
# ===========================================================================

def v_add(a: Point, b: Point) -> Point:
    return (a[0] + b[0], a[1] + b[1])


def v_sub(a: Point, b: Point) -> Point:
    return (a[0] - b[0], a[1] - b[1])


def v_scale(a: Point, s: float) -> Point:
    return (a[0] * s, a[1] * s)


def v_dot(a: Point, b: Point) -> float:
    return a[0] * b[0] + a[1] * b[1]


def v_cross(a: Point, b: Point) -> float:
    """2D cross product: a[0]*b[1] - a[1]*b[0]."""
    return a[0] * b[1] - a[1] * b[0]


def v_norm(a: Point) -> float:
    return math.hypot(a[0], a[1])


def v_dist(a: Point, b: Point) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def v_dist_sq(a: Point, b: Point) -> float:
    dx = a[0] - b[0]
    dy = a[1] - b[1]
    return dx * dx + dy * dy


def v_normalize(a: Point) -> Point:
    n = v_norm(a)
    if n == 0.0:
        return (0.0, 0.0)
    return (a[0] / n, a[1] / n)


def v_angle(a: Point, b: Point) -> float:
    """Angle between two vectors in radians."""
    d = v_dot(a, b)
    na = v_norm(a)
    nb = v_norm(b)
    if na == 0.0 or nb == 0.0:
        return 0.0
    cos_t = d / (na * nb)
    return math.acos(max(-1.0, min(1.0, cos_t)))


# ===========================================================================
# Line and polygon operations
# ===========================================================================

def line_intersection(p1: Point, p2: Point, p3: Point, p4: Point) -> Point | None:
    """Intersection point of lines (p1,p2) and (p3,p4). None if parallel."""
    x1, y1 = p1
    x2, y2 = p2
    x3, y3 = p3
    x4, y4 = p4
    denom = (x1 - x2) * (y3 - y4) - (y1 - y2) * (x3 - x4)
    if abs(denom) < 1e-15:
        return None
    t = ((x1 - x3) * (y3 - y4) - (y1 - y3) * (x3 - x4)) / denom
    return (x1 + t * (x2 - x1), y1 + t * (y2 - y1))


def segment_intersect(p1: Point, p2: Point, p3: Point, p4: Point) -> bool:
    """Check if line segments (p1,p2) and (p3,p4) intersect."""
    def _orient(a: Point, b: Point, c: Point) -> float:
        val = (b[1] - a[1]) * (c[0] - b[0]) - (b[0] - a[0]) * (c[1] - b[1])
        if val > 1e-15:
            return 1
        elif val < -1e-15:
            return -1
        return 0

    o1 = _orient(p1, p2, p3)
    o2 = _orient(p1, p2, p4)
    o3 = _orient(p3, p4, p1)
    o4 = _orient(p3, p4, p2)

    if o1 != o2 and o3 != o4:
        return True
    if o1 == 0 and _on_segment(p1, p3, p2):
        return True
    if o2 == 0 and _on_segment(p1, p4, p2):
        return True
    if o3 == 0 and _on_segment(p3, p1, p4):
        return True
    if o4 == 0 and _on_segment(p3, p2, p4):
        return True
    return False


def _on_segment(a: Point, b: Point, c: Point) -> bool:
    return (min(a[0], c[0]) <= b[0] <= max(a[0], c[0])
            and min(a[1], c[1]) <= b[1] <= max(a[1], c[1]))


def polygon_area(poly: list[Point]) -> float:
    """Shoelace formula for polygon area (signed)."""
    n = len(poly)
    if n < 3:
        return 0.0
    s = 0.0
    for i in range(n):
        j = (i + 1) % n
        s += poly[i][0] * poly[j][1] - poly[j][0] * poly[i][1]
    return abs(s) / 2.0


def polygon_perimeter(poly: list[Point]) -> float:
    n = len(poly)
    if n < 2:
        return 0.0
    total = 0.0
    for i in range(n):
        j = (i + 1) % n
        total += v_dist(poly[i], poly[j])
    return total


def point_in_polygon(p: Point, poly: list[Point]) -> bool:
    """Ray-casting algorithm for point-in-polygon test."""
    x, y = p
    n = len(poly)
    inside = False
    j = n - 1
    for i in range(n):
        xi, yi = poly[i]
        xj, yj = poly[j]
        if ((yi > y) != (yj > y)):
            x_intersect = (xj - xi) * (y - yi) / (yj - yi) + xi
            if x < x_intersect:
                inside = not inside
        j = i
    return inside


def polygon_centroid(poly: list[Point]) -> Point:
    """Centroid of a polygon (area-weighted)."""
    n = len(poly)
    if n < 3:
        # Fallback: average of points
        return (sum(p[0] for p in poly) / n, sum(p[1] for p in poly) / n)
    cx = 0.0
    cy = 0.0
    a = 0.0
    for i in range(n):
        j = (i + 1) % n
        cross = poly[i][0] * poly[j][1] - poly[j][0] * poly[i][1]
        a += cross
        cx += (poly[i][0] + poly[j][0]) * cross
        cy += (poly[i][1] + poly[j][1]) * cross
    a /= 2.0
    if abs(a) < 1e-15:
        return (sum(p[0] for p in poly) / n, sum(p[1] for p in poly) / n)
    return (cx / (6.0 * a), cy / (6.0 * a))


# ===========================================================================
# Convex hull
# ===========================================================================

def convex_hull(points: list[Point]) -> list[Point]:
    """Monotone chain (Andrew's) convex hull. Returns hull in CCW order."""
    if len(points) <= 1:
        return list(points)

    sorted_pts = sorted(set(points))
    if len(sorted_pts) <= 2:
        return list(sorted_pts)

    def _cross(o: Point, a: Point, b: Point) -> float:
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lower: list[Point] = []
    for p in sorted_pts:
        while len(lower) >= 2 and _cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)

    upper: list[Point] = []
    for p in reversed(sorted_pts):
        while len(upper) >= 2 and _cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)

    # Remove duplicate endpoints
    hull = lower[:-1] + upper[:-1]
    return hull


def is_convex(poly: list[Point]) -> bool:
    """Check if a polygon is convex (all turns same direction)."""
    n = len(poly)
    if n < 3:
        return True
    sign = 0
    for i in range(n):
        o = poly[i]
        a = poly[(i + 1) % n]
        b = poly[(i + 2) % n]
        cross = (a[0] - o[0]) * (b[1] - a[1]) - (a[1] - o[1]) * (b[0] - a[0])
        if abs(cross) < 1e-15:
            continue
        if sign == 0:
            sign = 1 if cross > 0 else -1
        elif (cross > 0) != (sign > 0):
            return False
    return True


# ===========================================================================
# Voronoi diagram (brute-force)
# ===========================================================================

def nearest_site(p: Point, sites: list[Point]) -> int:
    """Index of the nearest site to point p."""
    best_idx = 0
    best_d = v_dist_sq(p, sites[0])
    for i in range(1, len(sites)):
        d = v_dist_sq(p, sites[i])
        if d < best_d:
            best_d = d
            best_idx = i
    return best_idx


def voronoi_cell_bounds(
    sites: list[Point], i: int, bbox: tuple[float, float, float, float]
) -> list[Point]:
    """Approximate a Voronoi cell for site i by grid sampling within bbox.

    bbox = (xmin, ymin, xmax, ymax). Returns the cell boundary polygon.
    """
    xmin, ymin, xmax, ymax = bbox
    resolution = 40
    dx = (xmax - xmin) / resolution
    dy = (ymax - ymin) / resolution

    cell_points: list[Point] = []
    for gx in range(resolution + 1):
        for gy in range(resolution + 1):
            x = xmin + gx * dx
            y = ymin + gy * dy
            if nearest_site((x, y), sites) == i:
                cell_points.append((x, y))

    if not cell_points:
        return []
    return convex_hull(cell_points)


def voronoi_diagram(sites: list[Point], bbox: tuple[float, float, float, float]) -> list[list[Point]]:
    """Compute all Voronoi cells for the given sites within bbox."""
    return [voronoi_cell_bounds(sites, i, bbox) for i in range(len(sites))]


# ===========================================================================
# k-d tree (nearest neighbor)
# ===========================================================================

class KDNode:
    __slots__ = ("point", "axis", "left", "right")

    def __init__(self, point: Point, axis: int):
        self.point = point
        self.axis = axis
        self.left: KDNode | None = None
        self.right: KDNode | None = None


class KDTree:
    """k-d tree for nearest-neighbor search in 2D."""

    def __init__(self, points: list[Point]):
        if not points:
            raise ValueError("Cannot build KD-tree from empty point list")
        self.root = self._build(points, axis=0)

    @staticmethod
    def _build(points: list[Point], axis: int) -> KDNode:
        points = sorted(points, key=lambda p: p[axis])
        mid = len(points) // 2
        node = KDNode(points[mid], axis)
        next_axis = 1 - axis
        if mid > 0:
            node.left = KDTree._build(points[:mid], next_axis)
        if mid + 1 < len(points):
            node.right = KDTree._build(points[mid + 1:], next_axis)
        return node

    def nearest(self, target: Point) -> Point:
        """Find the nearest point to target."""
        best = [None, float("inf")]
        self._nearest_search(self.root, target, best)
        return best[0]  # type: ignore[return-value]

    def _nearest_search(self, node: KDNode, target: Point, best: list) -> None:
        if node is None:
            return
        d = v_dist_sq(node.point, target)
        if d < best[1]:
            best[0] = node.point
            best[1] = d
        axis = node.axis
        diff = target[axis] - node.point[axis]
        if diff <= 0:
            self._nearest_search(node.left, target, best)
            if diff**2 < best[1]:
                self._nearest_search(node.right, target, best)
        else:
            self._nearest_search(node.right, target, best)
            if diff**2 < best[1]:
                self._nearest_search(node.left, target, best)

    def k_nearest(self, target: Point, k: int) -> list[Point]:
        """Find the k nearest points to target."""
        results: list[tuple[float, Point]] = []
        self._k_nearest_search(self.root, target, k, results)
        results.sort(key=lambda x: x[0])
        return [pt for _, pt in results]

    def _k_nearest_search(self, node: KDNode, target: Point, k: int, results: list) -> None:
        if node is None:
            return
        d = v_dist_sq(node.point, target)
        results.append((d, node.point))
        if len(results) > k:
            results.sort(key=lambda x: x[0])
            results.pop()
        axis = node.axis
        diff = target[axis] - node.point[axis]
        if diff <= 0:
            self._k_nearest_search(node.left, target, k, results)
            if diff**2 < (results[-1][0] if results else float("inf")):
                self._k_nearest_search(node.right, target, k, results)
        else:
            self._k_nearest_search(node.right, target, k, results)
            if diff**2 < (results[-1][0] if results else float("inf")):
                self._k_nearest_search(node.left, target, k, results)
