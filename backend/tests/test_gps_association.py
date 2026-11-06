import tempfile
import unittest
from pathlib import Path

from app.services.gps_association import GPSAssociator, GPSSample, load_gps_csv


class GPSAssociationTests(unittest.TestCase):
    def setUp(self):
        self.samples = [
            GPSSample(0, 0.0, 29.6857, 76.9905, 5.0, "synthetic", True),
            GPSSample(1, 1000.0, 29.6858, 76.9906, 7.0, "synthetic", True),
            GPSSample(2, 2000.0, 29.6859, 76.9907, 6.0, "synthetic", True),
        ]
        self.associator = GPSAssociator(self.samples)

    def test_interpolates_between_bracketing_samples(self):
        match = self.associator.associate(500.0)
        self.assertEqual(match.method, "linear_interpolation")
        self.assertAlmostEqual(match.latitude, 29.68575)
        self.assertAlmostEqual(match.longitude, 76.99055)
        self.assertEqual(match.accuracy_m, 7.0)
        self.assertTrue(match.is_simulated)

    def test_nearest_sample_within_tolerance(self):
        match = self.associator.associate(2900.0)
        self.assertEqual(match.method, "nearest_sample")
        self.assertEqual(match.before_sample_index, 2)
        self.assertEqual(match.time_delta_ms, 900.0)

    def test_rejects_stale_sample(self):
        self.assertIsNone(self.associator.associate(5000.0))

    def test_missing_frame_time_returns_no_location(self):
        self.assertIsNone(self.associator.associate(None))

    def test_csv_requires_explicit_simulation_flag_for_synthetic_source(self):
        content = (
            "elapsed_ms,latitude,longitude,accuracy_m,source,is_simulated\n"
            "0,29.6,76.9,5,synthetic,false\n"
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "gps.csv"
            path.write_text(content, encoding="utf-8")
            with self.assertRaises(ValueError):
                load_gps_csv(path)


if __name__ == "__main__":
    unittest.main()
