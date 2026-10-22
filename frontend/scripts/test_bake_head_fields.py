"""Run with the pinned backend Python; independent nearest-triangle regression."""
import importlib.util
import unittest
from pathlib import Path

import numpy as np

spec = importlib.util.spec_from_file_location("baker", Path(__file__).with_name("bake-test-head-fields.py"))
assert spec and spec.loader
baker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(baker)


class NearestSurfaceTests(unittest.TestCase):
    def test_projects_interior_edges_and_vertices_with_correct_barycentrics(self):
        triangle = np.array([[[0., 0., 0.], [2., 0., 0.], [0., 2., 0.]]])
        points = np.array([[.5, .5, 1], [1.5, 1.5, 0], [-2, -1, 0]])
        distances, weights = baker.closest_points(points[:, None, :], triangle[None, :, :, :])
        np.testing.assert_allclose(distances[:, 0], [1, .5, 5])
        np.testing.assert_allclose(weights[:, 0], [[.5, .25, .25], [0, .5, .5], [1, 0, 0]])

    def test_radius_pruning_agrees_with_exhaustive_triangle_search(self):
        rng = np.random.default_rng(481)
        # Large triangles and tiny disconnected triangles make nearest-centroid
        # selection unreliable; the production search must still find the face.
        triangles = rng.normal(size=(250, 3, 3)) * rng.uniform(.001, .8, (250, 1, 1))
        triangles += rng.normal(size=(250, 1, 3))
        points = rng.uniform(-3, 3, (200, 3))
        ids, weights = baker.nearest_surface(points, triangles)
        exhaustive, _ = baker.closest_points(points[:, None, :], triangles[None, :, :, :])
        actual = np.sum((np.sum(triangles[ids] * weights[..., None], axis=1) - points) ** 2, axis=1)
        np.testing.assert_allclose(actual, exhaustive.min(axis=1), atol=1e-10)
        np.testing.assert_allclose(weights.sum(axis=1), 1, atol=1e-10)
        self.assertGreaterEqual(weights.min(), -1e-10)


if __name__ == "__main__":
    unittest.main()
