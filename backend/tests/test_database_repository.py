import sqlite3
import tempfile
import unittest
from pathlib import Path

from app.database import database
from app.database.repository import (
    add_observation,
    create_incident,
    create_track,
    get_incident_report_context,
    update_incident_after_observation,
)


class DatabaseRepositoryTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.original_path = database.DATABASE_PATH
        database.DATABASE_PATH = Path(self.temp_dir.name) / "test.db"
        database.initialize_database()

    def tearDown(self):
        database.DATABASE_PATH = self.original_path
        self.temp_dir.cleanup()

    def test_track_and_repeated_observations_roll_up_to_one_incident(self):
        timestamp = "2026-11-06T12:00:00+00:00"
        location = {
            "latitude": 0.1,
            "longitude": 0.2,
            "accuracy_m": 4.0,
            "delta_seconds": 0.1,
            "location_source": "synthetic-test",
            "is_simulated": True,
            "location_status": "associated",
        }
        incident_id = create_incident("session-a", timestamp, 0.75, location)
        track_id = create_track(
            "session-a", 11, timestamp, 0.75, (1, 2, 30, 40), None, incident_id
        )
        add_observation(
            track_id, timestamp, 0.75, (1, 2, 30, 40), 0.0, "test", location
        )
        update_incident_after_observation(incident_id, timestamp, 0.75, location)
        add_observation(
            track_id, timestamp, 0.91, (1, 2, 30, 40), 0.1, "test", location
        )
        update_incident_after_observation(incident_id, timestamp, 0.91, location)

        context = get_incident_report_context(incident_id)
        self.assertEqual(context["observation_count"], 2)
        self.assertEqual(context["track_count"], 1)
        self.assertAlmostEqual(context["best_confidence"], 0.91)
        self.assertTrue(context["is_simulated"])
        self.assertEqual(context["latitude"], 0.1)

    def test_existing_database_is_migrated_without_fabricating_gps(self):
        legacy_path = Path(self.temp_dir.name) / "legacy.db"
        conn = sqlite3.connect(legacy_path)
        conn.execute("""
            CREATE TABLE pothole_tracks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                track_id INTEGER NOT NULL,
                first_seen TEXT NOT NULL,
                last_seen TEXT NOT NULL,
                best_confidence REAL NOT NULL,
                x1 INTEGER, y1 INTEGER, x2 INTEGER, y2 INTEGER,
                crop_path TEXT,
                UNIQUE(session_id, track_id)
            )
        """)
        conn.execute("""
            CREATE TABLE observations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                pothole_id INTEGER NOT NULL,
                timestamp TEXT NOT NULL,
                confidence REAL NOT NULL,
                x1 INTEGER, y1 INTEGER, x2 INTEGER, y2 INTEGER
            )
        """)
        conn.execute(
            "INSERT INTO pothole_tracks(session_id,track_id,first_seen,last_seen,best_confidence) VALUES(?,?,?,?,?)",
            ("legacy", 3, "2026-01-01T00:00:00+00:00", "2026-01-01T00:00:01+00:00", 0.8),
        )
        conn.commit()
        conn.close()

        database.DATABASE_PATH = legacy_path
        database.initialize_database()
        context_conn = database.get_connection()
        try:
            track = context_conn.execute("SELECT incident_id FROM pothole_tracks WHERE id = 1").fetchone()
            incident = context_conn.execute("SELECT latitude, longitude, location_status FROM incidents WHERE id = ?", (track["incident_id"],)).fetchone()
        finally:
            context_conn.close()
        self.assertIsNotNone(track["incident_id"])
        self.assertIsNone(incident["latitude"])
        self.assertIsNone(incident["longitude"])
        self.assertEqual(incident["location_status"], "unavailable")


if __name__ == "__main__":
    unittest.main()
