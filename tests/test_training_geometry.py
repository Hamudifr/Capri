"""Tests for the computational geometry training module."""

import math
import unittest

from research.training.geometry.core import (
    v_add, v_sub, v_scale, v_dot, v_cross, v_norm, v_dist, v_dist_sq,
    v_normalize, v_angle,
    line_intersection, segment_intersect,
    polygon_area, polygon_perimeter, point_in_polygon, polygon_centroid,
    convex_hull, is_convex,
    nearest_site, voronoi_cell_bounds, voronoi_diagram,
    KDTree,
)


class TestVectorOps(unittest.TestCase):

    def test_v_add(self):
        self.assertEqual(v_add((1, 2), (3, 4)), (4, 6))

    def test_v_sub(self):
        self.assertEqual(v_sub((5, 7), (2, 3)), (3, 4))

    def test_v_scale(self):
        self.assertEqual(v_scale((1, 2), 3.0), (3.0, 6.0))

    def test_v_dot(self):
        self.assertAlmostEqual(v_dot((1, 2), (3, 4)), 11.0)

    def test_v_cross(self):
        self.assertAlmostEqual(v_cross((1, 0), (0, 1)), 1.0)
        self.assertAlmostEqual(v_cross((2, 3), (4, 5)), 2 * 5 - 3 * 4)

    def test_v_norm(self):
        self.assertAlmostEqual(v_norm((3, 4)), 5.0)
        self.assertAlmostEqual(v_norm((0, 0)), 0.0)

    def test_v_dist(self):
        self.assertAlmostEqual(v_dist((0, 0), (3, 4)), 5.0)

    def test_v_dist_sq(self):
        self.assertAlmostEqual(v_dist_sq((0, 0), (3, 4)), 25.0)

    def test_v_normalize(self):
        n = v_normalize((3, 4))
        self.assertAlmostEqual(n[0], 0.6)
        self.assertAlmostEqual(n[1], 0.8)

    def test_v_normalize_zero(self):
        self.assertEqual(v_normalize((0, 0)), (0.0, 0.0))

    def test_v_angle(self):
        # 90 degrees
        angle = v_angle((1, 0), (0, 1))
        self.assertAlmostEqual(angle, math.pi / 2, places=5)
        # 0 degrees
        angle = v_angle((1, 0), (2, 0))
        self.assertAlmostEqual(angle, 0.0, places=5)


class TestLineIntersection(unittest.TestCase):

    def test_intersecting_lines(self):
        p = line_intersection((0, 0), (2, 2), (0, 2), (2, 0))
        self.assertAlmostEqual(p[0], 1.0, places=5)
        self.assertAlmostEqual(p[1], 1.0, places=5)

    def test_parallel_lines(self):
        p = line_intersection((0, 0), (1, 0), (0, 1), (1, 1))
        self.assertIsNone(p)

    def test_segment_intersect(self):
        self.assertTrue(segment_intersect((0, 0), (2, 2), (0, 2), (2, 0)))

    def test_segment_no_intersect(self):
        self.assertFalse(segment_intersect((0, 0), (1, 1), (2, 2), (3, 3)))


class TestPolygon(unittest.TestCase):

    def test_square_area(self):
        square = [(0, 0), (2, 0), (2, 2), (0, 2)]
        self.assertAlmostEqual(polygon_area(square), 4.0)

    def test_triangle_area(self):
        tri = [(0, 0), (3, 0), (0, 4)]
        self.assertAlmostEqual(polygon_area(tri), 6.0)

    def test_polygon_perimeter(self):
        square = [(0, 0), (2, 0), (2, 2), (0, 2)]
        self.assertAlmostEqual(polygon_perimeter(square), 8.0)

    def test_point_in_polygon(self):
        square = [(0, 0), (4, 0), (4, 4), (0, 4)]
        self.assertTrue(point_in_polygon((2, 2), square))
        self.assertFalse(point_in_polygon((5, 5), square))
        self.assertFalse(point_in_polygon((-1, 2), square))

    def test_polygon_centroid(self):
        square = [(0, 0), (2, 0), (2, 2), (0, 2)]
        cx, cy = polygon_centroid(square)
        self.assertAlmostEqual(cx, 1.0, places=5)
        self.assertAlmostEqual(cy, 1.0, places=5)


class TestConvexHull(unittest.TestCase):

    def test_square_hull(self):
        square = [(0, 0), (1, 1), (2, 0), (1, -1)]
        hull = convex_hull(square)
        self.assertEqual(len(hull), 4)
        # Hull should be convex
        self.assertTrue(is_convex(hull))

    def test_triangle_hull(self):
        tri = [(0, 0), (2, 0), (1, 2)]
        hull = convex_hull(tri)
        self.assertEqual(len(hull), 3)

    def test_collinear_points(self):
        pts = [(0, 0), (1, 0), (2, 0)]
        hull = convex_hull(pts)
        self.assertLessEqual(len(hull), 2)

    def test_is_convex(self):
        convex = [(0, 0), (2, 0), (2, 2), (0, 2)]
        self.assertTrue(is_convex(convex))
        # (1, 0.5) is inside the triangle (0,0), (2,0), (0,2) -> concave
        concave = [(0, 0), (2, 0), (1, 0.5), (0, 2)]
        self.assertFalse(is_convex(concave))


class TestVoronoi(unittest.TestCase):

    def test_nearest_site(self):
        sites = [(0, 0), (5, 5)]
        self.assertEqual(nearest_site((1, 1), sites), 0)
        self.assertEqual(nearest_site((4, 4), sites), 1)

    def test_voronoi_cell(self):
        sites = [(0, 0), (4, 0)]
        cell = voronoi_cell_bounds(sites, 0, (-1, -1, 5, 2))
        self.assertGreater(len(cell), 0)

    def test_voronoi_diagram(self):
        sites = [(0, 0), (3, 0), (1.5, 3)]
        cells = voronoi_diagram(sites, (-1, -1, 4, 4))
        self.assertEqual(len(cells), 3)
        for cell in cells:
            self.assertGreater(len(cell), 0)


class TestKDTree(unittest.TestCase):

    def test_nearest(self):
        points = [(0, 0), (1, 1), (2, 2), (3, 3), (10, 10)]
        tree = KDTree(points)
        nearest = tree.nearest((1.1, 1.1))
        self.assertAlmostEqual(nearest[0], 1.0, places=1)
        self.assertAlmostEqual(nearest[1], 1.0, places=1)

    def test_nearest_edge(self):
        points = [(5, 5), (10, 10)]
        tree = KDTree(points)
        nearest = tree.nearest((0, 0))
        self.assertEqual(nearest, (5, 5))

    def test_k_nearest(self):
        points = [(0, 0), (1, 0), (2, 0), (3, 0), (100, 100)]
        tree = KDTree(points)
        knn = tree.k_nearest((0, 0), 3)
        self.assertEqual(len(knn), 3)
        # Nearest should be (0, 0)
        self.assertEqual(knn[0], (0, 0))


if __name__ == "__main__":
    unittest.main()
