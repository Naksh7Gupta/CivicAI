import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

from app.database import database
from app.database.repository import get_incident_report_context
from app.services.detection_manager import DetectionManager
from app.services.gps_provider import LocationMatch


class TensorLike:
    def __init__(self, value):
        self.value = value

    def cpu(self):
        return self

    def numpy(self):
        return np.asarray(self.value)

    def int(self):
        return self

    def tolist(self):
        return list(self.value)


class Boxes:
    def __init__(self):
        self.xyxy = TensorLike([[1, 2, 20, 30]])
        self.id = TensorLike([5])
        self.conf = TensorLike([0.82])


class Result:
    boxes = Boxes()


class FakeGPS:
    def match(self, timestamp):
        return LocationMatch(
            latitude=0.1,
            longitude=0.2,
            accuracy_m=4.0,
            delta_seconds=0.1,
            location_source="synthetic-test",
            is_simulated=True,
            location_status="associated",
            sample_timestamp_seconds=timestamp,
        )


class DetectionManagerTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.original_path = database.DATABASE_PATH
        database.DATABASE_PATH = Path(self.temp_dir.name) / "test.db"
        database.initialize_database()

    def tearDown(self):
        database.DATABASE_PATH = self.original_path
        self.temp_dir.cleanup()

    def test_repeated_tracked_frames_become_one_incident_with_two_observations(self):
        with patch("app.services.detection_manager.CropStorage") as crop_storage:
            crop_storage.return_value.save_crop.return_value = None
            manager = DetectionManager("session-1", gps_provider=FakeGPS())
            manager.process(
                np.zeros((40, 40, 3), dtype=np.uint8),
                Result(),
                video_timestamp_seconds=0.0,
                timestamp_source="test",
            )
            manager.process(
                np.zeros((40, 40, 3), dtype=np.uint8),
                Result(),
                video_timestamp_seconds=0.1,
                timestamp_source="test",
            )

        context = get_incident_report_context(1)
        self.assertEqual(context["track_count"], 1)
        self.assertEqual(context["observation_count"], 2)
        self.assertTrue(context["is_simulated"])
        self.assertEqual(context["location_status"], "associated")


if __name__ == "__main__":
    unittest.main()
