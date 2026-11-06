import tempfile
import unittest
from pathlib import Path

from app.services.gps_provider import GPSLocationProvider


class GPSProviderTests(unittest.TestCase):
    def make_csv(self, content):
        temporary = tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False, encoding="utf-8")
        temporary.write(content)
        temporary.close()
        self.addCleanup(lambda: Path(temporary.name).unlink(missing_ok=True))
        return temporary.name

    def test_nearest_fix_is_associated_and_simulation_flag_is_preserved(self):
        path = self.make_csv(
            "video_timestamp_seconds,latitude,longitude,accuracy_m,location_source,is_simulated\n"
            "0.0,0.1,0.2,3.5,synthetic,true\n"
            "1.0,0.2,0.3,4.0,synthetic,true\n"
        )
        provider = GPSLocationProvider.from_csv(path, max_delta_seconds=0.6)
        match = provider.match(0.8)
        self.assertIsNotNone(match)
        self.assertEqual(match.latitude, 0.2)
        self.assertTrue(match.is_simulated)
        self.assertEqual(match.location_status, "associated")
        self.assertAlmostEqual(match.delta_seconds, 0.2)

    def test_stale_fix_is_not_associated(self):
        path = self.make_csv(
            "video_timestamp_seconds,latitude,longitude,accuracy_m,location_source,is_simulated\n"
            "0.0,0.1,0.2,3.5,gps,false\n"
        )
        provider = GPSLocationProvider.from_csv(path, max_delta_seconds=0.5)
        self.assertIsNone(provider.match(3.0))

    def test_accuracy_is_reported_not_silently_hidden(self):
        path = self.make_csv(
            "video_timestamp_seconds,latitude,longitude,accuracy_m,location_source,is_simulated\n"
            "0.0,0.1,0.2,90,gps,false\n"
        )
        provider = GPSLocationProvider.from_csv(path, max_accuracy_m=50)
        self.assertEqual(provider.match(0.0).location_status, "low_accuracy")

    def test_utc_samples_require_video_start_time(self):
        path = self.make_csv(
            "timestamp_utc,latitude,longitude,accuracy_m,location_source,is_simulated\n"
            "2026-01-01T00:00:01Z,0.1,0.2,4,gps,false\n"
        )
        with self.assertRaisesRegex(ValueError, "VIDEO_START_TIME_UTC"):
            GPSLocationProvider.from_csv(path)
        provider = GPSLocationProvider.from_csv(
            path, video_start_time_utc="2026-01-01T00:00:00Z"
        )
        self.assertIsNotNone(provider.match(1.0))

    def test_invalid_simulation_flag_is_rejected(self):
        path = self.make_csv(
            "video_timestamp_seconds,latitude,longitude,accuracy_m,location_source,is_simulated\n"
            "0.0,0.1,0.2,3.5,gps,maybe\n"
        )
        with self.assertRaisesRegex(ValueError, "is_simulated"):
            GPSLocationProvider.from_csv(path)


if __name__ == "__main__":
    unittest.main()
