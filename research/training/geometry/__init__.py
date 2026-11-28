"""Computational geometry: shapes, hulls, and spatial data structures."""

from research.training.geometry.core import (
    KDTree, KDNode,
    v_add, v_sub, v_scale, v_dot, v_cross, v_norm, v_dist, v_dist_sq,
    v_normalize, v_angle,
    line_intersection, segment_intersect,
    polygon_area, polygon_perimeter, point_in_polygon, polygon_centroid,
    convex_hull, is_convex,
    nearest_site, voronoi_cell_bounds, voronoi_diagram,
)
