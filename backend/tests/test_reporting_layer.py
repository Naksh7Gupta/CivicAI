import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

from app.database import database
from app.database.repository import add_observation, create_track, link_track_to_incident
from app.geolocation.association import GPSFix, GPSValidationError, associate_gps_fixes
from app.geolocation.csv_import import import_gps_csv
from app.geolocation.repository import save_gps_fix, associate_session_fix
from app.services.detection_manager import DetectionManager
from app.services.reporting import (LLMConfigurationError, OpenAICompatibleClient,
                                     build_incident_context, generate_incident_report)


class FakeTensor:
    def __init__(self, value):
        self.value = value
    def cpu(self):
        return self
    def numpy(self):
        return self.value
    def tolist(self):
        return self.value
    def int(self):
        return self


class FakeClient:
    model = "test-model"
    def generate_narrative(self, report_type, context):
        return "The stored record contains model observations. Field verification is still required."


class ReportingLayerTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        database.DATABASE_PATH = Path(self.temp_dir.name) / "test.db"
        database.initialize_database()
        self.start = datetime(2026, 11, 7, 10, 0, tzinfo=timezone.utc)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_gps_interpolation_and_quality_gate(self):
        fixes = [
            GPSFix(self.start, 29.68, 76.98, 4.0, id=1),
            GPSFix(self.start + timedelta(seconds=2), 29.6802, 76.9802, 5.0, id=2),
        ]
        result = associate_gps_fixes(fixes, self.start + timedelta(seconds=1))
        self.assertEqual(result.method, "linear_interpolation")
        self.assertAlmostEqual(result.latitude, 29.6801)
        self.assertEqual(result.accuracy_m, 5.0)
        self.assertIsNone(associate_gps_fixes(
            [GPSFix(self.start, 29.68, 76.98, 30.0)],
            self.start + timedelta(seconds=1),
        ))

    def test_rejects_naive_time_and_unlabelled_synthetic_coordinates(self):
        with self.assertRaises(GPSValidationError):
            associate_gps_fixes([], datetime(2026, 11, 7, 10, 0))
        with self.assertRaises(GPSValidationError):
            GPSFix(self.start, 29.68, 76.98, 4.0, source="synthetic").validated()

    def test_gps_csv_import_and_repository_interpolation(self):
        path = Path(self.temp_dir.name) / "gps.csv"
        path.write_text(
            "recorded_at,latitude,longitude,accuracy_m\n"
            "2026-11-07T10:00:00+00:00,29.68,76.98,4\n"
            "2026-11-07T10:00:02+00:00,29.6802,76.9802,5\n",
            encoding="utf-8",
        )
        count = import_gps_csv("session-gps", path, source="synthetic", is_simulated=True)
        self.assertEqual(count, 2)
        result = associate_session_fix("session-gps", self.start + timedelta(seconds=1))
        self.assertEqual(result.method, "linear_interpolation")
        self.assertTrue(result.is_simulated)

    def test_detection_manager_groups_same_tracker_and_persists_gps_provenance(self):
        save_gps_fix("session-track", self.start, 29.68, 76.98, 4,
                     source="synthetic", is_simulated=True)
        save_gps_fix("session-track", self.start + timedelta(seconds=1), 29.6801, 76.9801, 5,
                     source="synthetic", is_simulated=True)
        boxes = SimpleNamespace(
            xyxy=FakeTensor(np.array([[10, 10, 40, 40]], dtype=float)),
            id=FakeTensor([7]),
            conf=FakeTensor([0.82]),
        )
        manager = DetectionManager("session-track")
        with patch("app.services.detection_manager.CropStorage.save_crop", return_value=None):
            manager.process(None, SimpleNamespace(boxes=boxes), self.start + timedelta(milliseconds=500))
            manager.process(None, SimpleNamespace(boxes=boxes), self.start + timedelta(milliseconds=700))
        connection = database.get_connection()
        incident = connection.execute("SELECT * FROM incidents").fetchone()
        observations = connection.execute("SELECT * FROM observations ORDER BY id").fetchall()
        connection.close()
        self.assertEqual(incident["observation_count"], 2)
        self.assertEqual(len(observations), 2)
        self.assertEqual(observations[0]["location_source"], "synthetic")
        self.assertEqual(observations[0]["is_simulated"], 1)
        self.assertEqual(incident["location_basis"], "camera_position_estimate")

    def test_missing_tracker_ids_are_not_merged(self):
        boxes = SimpleNamespace(
            xyxy=FakeTensor(np.array([[10, 10, 40, 40]], dtype=float)),
            id=None,
            conf=FakeTensor([0.71]),
        )
        manager = DetectionManager("session-untracked")
        with patch("app.services.detection_manager.CropStorage.save_crop", return_value=None):
            manager.process(None, SimpleNamespace(boxes=boxes))
            manager.process(None, SimpleNamespace(boxes=boxes))
        connection = database.get_connection()
        count = connection.execute("SELECT COUNT(*) FROM incidents").fetchone()[0]
        connection.close()
        self.assertEqual(count, 2)

    def test_legacy_track_observations_are_backfilled_to_incident(self):
        track_id = create_track("legacy-session", 3, "t1", 0.8, (1, 2, 3, 4), None)
        add_observation(track_id, "t1", 0.8, (1, 2, 3, 4))
        incident_id = 1
        from app.services.incident_aggregator import create_incident
        incident_id = create_incident("legacy-session", 3, "t2", 0.9)
        link_track_to_incident(track_id, incident_id)
        connection = database.get_connection()
        incident = connection.execute("SELECT * FROM incidents WHERE id=?", (incident_id,)).fetchone()
        observation = connection.execute("SELECT * FROM observations WHERE pothole_id=?", (track_id,)).fetchone()
        connection.close()
        self.assertEqual(incident["observation_count"], 1)
        self.assertEqual(observation["incident_id"], incident_id)

    def test_missing_llm_configuration_fails_clearly(self):
        with patch.dict("os.environ", {}, clear=True):
            with self.assertRaises(LLMConfigurationError):
                OpenAICompatibleClient.from_environment()

    def test_report_context_marks_missing_and_simulated_facts(self):
        connection = database.get_connection()
        connection.execute(
            """INSERT INTO incidents (
                 session_id, track_id, first_seen, last_seen, best_confidence,
                 observation_count, reference_latitude, reference_longitude,
                 gps_accuracy_m, location_source, is_simulated, location_basis
               ) VALUES ('s', 1, 't1', 't2', .9, 1, 29.68, 76.98, 4,
                         'synthetic', 1, 'camera_position_estimate')"""
        )
        connection.commit()
        connection.close()
        context = build_incident_context(1)
        self.assertTrue(any("simulated" in item.lower()
                            for item in context["missing_or_unverified_information"]))
        self.assertTrue(any("inspection" in item.lower()
                            for item in context["missing_or_unverified_information"]))

    def test_fake_llm_report_is_saved_with_its_evidence_context(self):
        connection = database.get_connection()
        connection.execute(
            """INSERT INTO incidents (
                 session_id, track_id, first_seen, last_seen, best_confidence,
                 observation_count
               ) VALUES ('s', 2, 't1', 't1', .75, 0)"""
        )
        connection.commit()
        connection.close()
        report = generate_incident_report(1, client=FakeClient())
        self.assertEqual(report["model"], "test-model")
        connection = database.get_connection()
        saved = connection.execute(
            "SELECT * FROM generated_reports WHERE id=?", (report["report_id"],)
        ).fetchone()
        connection.close()
        self.assertEqual(saved["report_type"], "incident")
        self.assertIn("interpretation_limits", json.loads(saved["context_json"]))


if __name__ == "__main__":
    unittest.main()
