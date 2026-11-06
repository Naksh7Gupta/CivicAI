import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from app.database import database as database_module
from app.database.database import initialize_database
from app.database.repository import create_track, add_observation
from app.database.reporting_repository import save_gps_samples, save_observation_location
from app.services.gps_association import GPSSample, GPSAssociator
from app.services.incident_aggregation import IncidentAggregator
from app.services.reporting import ReportingService


class ReportingIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "civicai-test.db"
        self.database_patch = patch.object(database_module, "DATABASE_PATH", self.db_path)
        self.database_patch.start()
        initialize_database()

    def tearDown(self):
        self.database_patch.stop()
        self.temp_dir.cleanup()

    def add_track(self, session_id, tracker_id, timestamp, gps_source="synthetic", simulated=True):
        track_id = create_track(
            session_id,
            tracker_id,
            timestamp,
            0.82,
            (10, 20, 80, 90),
            None,
            image=b"test-image",
        )
        observation_id = add_observation(
            track_id, timestamp, 0.82, (10, 20, 80, 90)
        )
        sample = GPSSample(
            sample_index=0,
            elapsed_ms=500.0,
            latitude=29.6857,
            longitude=76.9905,
            accuracy_m=5.0,
            source=gps_source,
            is_simulated=simulated,
        )
        save_gps_samples(session_id, [sample])
        match = GPSAssociator([sample]).associate(500.0)
        save_observation_location(session_id, observation_id, 500.0, match)
        return track_id

    def test_repeated_nearby_tracks_merge_and_report_stays_cautious(self):
        now = datetime.now(timezone.utc)
        first = self.add_track("session-a", 1, now.isoformat())
        second = self.add_track(
            "session-b", 1, (now + timedelta(seconds=1)).isoformat()
        )

        aggregator = IncidentAggregator()
        first_incident = aggregator.assign_track(first)
        second_incident = aggregator.assign_track(second)

        self.assertEqual(first_incident, second_incident)
        packet = ReportingService().build_incident_evidence(first_incident)
        self.assertEqual(packet["verified_facts"]["track_count"], 2)
        self.assertEqual(packet["verified_facts"]["observation_count"], 2)
        self.assertTrue(packet["verified_facts"]["location"]["is_simulated"])
        self.assertTrue(
            any("synthetic test data" in item for item in packet["limitations"])
        )
        self.assertTrue(
            any("not a measurement of physical severity" in item for item in packet["limitations"])
        )

    def test_real_and_synthetic_traces_are_not_merged(self):
        now = datetime.now(timezone.utc)
        synthetic_track = self.add_track("session-sim", 1, now.isoformat())
        real_track = self.add_track(
            "session-real", 1, (now + timedelta(seconds=1)).isoformat(),
            gps_source="phone_gps", simulated=False,
        )

        aggregator = IncidentAggregator()
        synthetic_incident = aggregator.assign_track(synthetic_track)
        real_incident = aggregator.assign_track(real_track)
        self.assertNotEqual(synthetic_incident, real_incident)

    def test_create_track_persists_image_and_observation_id(self):
        timestamp = datetime.now(timezone.utc).isoformat()
        track_id = create_track(
            "session-image", 5, timestamp, 0.9,
            (1, 2, 30, 40), None, image=b"jpeg-bytes",
        )
        observation_id = add_observation(
            track_id, timestamp, 0.9, (1, 2, 30, 40)
        )
        connection = database_module.get_connection()
        try:
            row = connection.execute(
                "SELECT image FROM pothole_tracks WHERE id = ?", (track_id,)
            ).fetchone()
            self.assertEqual(row["image"], b"jpeg-bytes")
            self.assertGreater(observation_id, 0)
        finally:
            connection.close()


if __name__ == "__main__":
    unittest.main()
