import tempfile
import unittest
from pathlib import Path

from app.database import database
from app.database.repository import create_incident, create_track
from app.api import list_potholes


class APITests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.original_path = database.DATABASE_PATH
        database.DATABASE_PATH = Path(self.temp_dir.name) / "test.db"
        database.initialize_database()

    def tearDown(self):
        database.DATABASE_PATH = self.original_path
        self.temp_dir.cleanup()

    def test_api_does_not_derive_severity_from_confidence_or_invent_gps(self):
        timestamp = "2026-11-06T12:00:00+00:00"
        incident_id = create_incident("session", timestamp, 0.99, None)
        create_track("session", 1, timestamp, 0.99, (0, 0, 10, 10), None, incident_id)
        records = list_potholes()
        self.assertEqual(records[0]["severity"], "Not assessed")
        self.assertIsNone(records[0]["latitude"])
        self.assertIsNone(records[0]["longitude"])
        self.assertIn("unavailable", records[0]["address"].lower())


if __name__ == "__main__":
    unittest.main()
