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
from app.ingestion.stream_receiver import StreamReceiver
from app.services.detection_manager import DetectionManager
from app.services.incident_aggregator import create_incident, record_incident_observation
from app.services.reporting import (LLMConfigurationError, OpenAICompatibleClient,
                                     build_area_context, build_incident_context,
                                     generate_incident_report)


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

    def test_poor_accuracy_fix_does_not_hide_nearby_accurate_fix(self):
        save_gps_fix("quality-session", self.start, 29.68, 76.98, 4.0)
        save_gps_fix("quality-session", self.start + timedelta(seconds=1),
                     29.681, 76.981, 40.0)
        result = associate_session_fix(
            "quality-session", self.start + timedelta(milliseconds=1100)
        )
        self.assertIsNotNone(result)
        self.assertEqual(result.method, "nearest")
        self.assertEqual(result.latitude, 29.68)

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
        self.assertEqual(observations[0]["timestamp"], (self.start + timedelta(milliseconds=500)).isoformat())
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

    def test_area_report_rejects_reversed_date_range(self):
        with self.assertRaises(ValueError):
            build_area_context(
                start="2026-11-08T00:00:00+00:00",
                end="2026-11-07T00:00:00+00:00",
            )
        context = build_area_context()
        self.assertIn("no polygon", context["scope"].lower())

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


    def test_rtsp_and_camera_sources_are_not_misclassified_as_video_files(self):
        self.assertFalse(StreamReceiver("rtsp://camera.example/live").is_file_source)
        self.assertFalse(StreamReceiver(0).is_file_source)
        local_video = Path(self.temp_dir.name) / "recording.mp4"
        local_video.touch()
        self.assertTrue(StreamReceiver(local_video).is_file_source)

    def test_real_gps_replaces_synthetic_incident_reference(self):
        synthetic = GPSFix(
            self.start, 29.68, 76.98, 2.0,
            source="synthetic", is_simulated=True,
        ).validated()
        real = GPSFix(
            self.start + timedelta(seconds=1), 29.69, 76.99, 12.0,
            source="gps", is_simulated=False,
        ).validated()
        incident_id = create_incident("mixed-source-session", 1, "t1", 0.8, synthetic)
        record_incident_observation(incident_id, "t2", 0.9, real)
        connection = database.get_connection()
        incident = connection.execute(
            "SELECT * FROM incidents WHERE id=?", (incident_id,)
        ).fetchone()
        connection.close()
        self.assertEqual(incident["location_source"], "gps")
        self.assertEqual(incident["is_simulated"], 0)
        self.assertEqual(incident["reference_latitude"], 29.69)

    def test_area_report_includes_overlapping_incidents_and_window_counts(self):
        first_seen = self.start - timedelta(hours=1)
        last_seen = self.start + timedelta(hours=2)
        incident_id = create_incident(
            "area-window-session", 4, first_seen.isoformat(), 0.8
        )
        track_id = create_track(
            "area-window-session", 4, first_seen.isoformat(), 0.8,
            (1, 2, 3, 4), None, incident_id=incident_id,
        )
        timestamps = [
            first_seen,
            self.start + timedelta(minutes=30),
            last_seen,
        ]
        for timestamp in timestamps:
            add_observation(
                track_id, timestamp.isoformat(), 0.8, (1, 2, 3, 4),
                incident_id=incident_id,
            )
        connection = database.get_connection()
        connection.execute(
            "UPDATE incidents SET last_seen=?, observation_count=3 WHERE id=?",
            (last_seen.isoformat(), incident_id),
        )
        connection.commit()
        connection.close()

        context = build_area_context(
            start=self.start.isoformat(),
            end=(self.start + timedelta(hours=1)).isoformat(),
        )
        self.assertEqual(context["incident_count"], 1)
        self.assertEqual(context["observation_count"], 3)
        self.assertEqual(context["observations_in_selected_window"], 1)
        self.assertEqual(
            context["incidents"][0]["observations_in_selected_window"], 1
        )

if __name__ == "__main__":
    unittest.main()
