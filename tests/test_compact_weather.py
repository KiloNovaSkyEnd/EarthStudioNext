import unittest
import numpy as np
from ges_next.compact_weather import reduce_rgba2


class CompactWeatherTests(unittest.TestCase):
    def test_opaque_average_and_rounding(self):
        source = np.array([[[0, 10, 30, 255], [100, 10, 30, 255]],
                           [[200, 10, 30, 255], [255, 10, 30, 255]]], dtype=np.uint8)
        self.assertEqual(reduce_rgba2(source).tolist(), [[[139, 10, 30, 255]]])

    def test_limb_does_not_mix_in_invalid_black(self):
        source = np.zeros((2, 2, 4), dtype=np.uint8)
        source[0, 0] = [200, 120, 50, 255]
        self.assertEqual(reduce_rgba2(source).tolist(), [[[200, 120, 50, 64]]])

    def test_missing_remains_transparent(self):
        source = np.full((2, 2, 4), 100, dtype=np.uint8)
        source[:, :, 3] = 0
        self.assertEqual(reduce_rgba2(source).tolist(), [[[0, 0, 0, 0]]])

    def test_strips_equal_whole_image(self):
        source = np.random.default_rng(7).integers(0, 256, (16, 12, 4), dtype=np.uint8)
        strips = np.concatenate([reduce_rgba2(source[row:row + 4]) for row in range(0, 16, 4)])
        np.testing.assert_array_equal(strips, reduce_rgba2(source))
