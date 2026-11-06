"""Database connection management."""
import sqlite3
from pathlib import Path

from app.core.config import DATABASE_PATH


def get_connection():

    DATABASE_PATH.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    conn = sqlite3.connect(DATABASE_PATH)

    conn.row_factory = sqlite3.Row

    conn.execute("PRAGMA journal_mode=WAL")

    conn.execute("PRAGMA foreign_keys=ON")

    return conn


def initialize_database():

    conn = get_connection()

    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS pothole_tracks (

            id INTEGER PRIMARY KEY AUTOINCREMENT,

            session_id TEXT NOT NULL,

            track_id INTEGER NOT NULL,

            first_seen TEXT NOT NULL,

            last_seen TEXT NOT NULL,

            best_confidence REAL NOT NULL,

            x1 INTEGER,
            y1 INTEGER,
            x2 INTEGER,
            y2 INTEGER,

            crop_path TEXT,
            image BLOB,
            image_mime TEXT NOT NULL DEFAULT 'image/jpeg',

            UNIQUE(session_id, track_id)
        )
    """)

    columns = {
        row["name"]
        for row in cursor.execute("PRAGMA table_info(pothole_tracks)").fetchall()
    }
    if "image" not in columns:
        cursor.execute("ALTER TABLE pothole_tracks ADD COLUMN image BLOB")
    if "image_mime" not in columns:
        cursor.execute(
            "ALTER TABLE pothole_tracks ADD COLUMN image_mime TEXT NOT NULL DEFAULT 'image/jpeg'"
        )
    for row in cursor.execute(
        "SELECT id, crop_path FROM pothole_tracks WHERE image IS NULL AND crop_path IS NOT NULL"
    ).fetchall():
        image_path = Path(row["crop_path"])
        if image_path.is_file():
            cursor.execute(
                "UPDATE pothole_tracks SET image = ?, image_mime = 'image/jpeg' WHERE id = ?",
                (image_path.read_bytes(), row["id"]),
            )

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS observations (

            id INTEGER PRIMARY KEY AUTOINCREMENT,

            pothole_id INTEGER NOT NULL,

            timestamp TEXT NOT NULL,

            confidence REAL NOT NULL,

            x1 INTEGER,
            y1 INTEGER,
            x2 INTEGER,
            y2 INTEGER,

            FOREIGN KEY(pothole_id)
                REFERENCES pothole_tracks(id)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS gps_samples (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            sample_index INTEGER NOT NULL,
            elapsed_ms REAL NOT NULL,
            latitude REAL NOT NULL CHECK(latitude >= -90 AND latitude <= 90),
            longitude REAL NOT NULL CHECK(longitude >= -180 AND longitude <= 180),
            accuracy_m REAL,
            source TEXT NOT NULL,
            is_simulated INTEGER NOT NULL DEFAULT 0,
            UNIQUE(session_id, sample_index)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS observation_locations (
            observation_id INTEGER PRIMARY KEY,
            session_id TEXT NOT NULL,
            frame_elapsed_ms REAL NOT NULL,
            latitude REAL NOT NULL,
            longitude REAL NOT NULL,
            accuracy_m REAL,
            location_source TEXT NOT NULL,
            is_simulated INTEGER NOT NULL DEFAULT 0,
            method TEXT NOT NULL,
            gps_before_sample_id INTEGER,
            gps_after_sample_id INTEGER,
            time_delta_ms REAL,
            location_semantics TEXT NOT NULL DEFAULT 'vehicle_position_estimate',
            FOREIGN KEY(observation_id) REFERENCES observations(id) ON DELETE CASCADE,
            FOREIGN KEY(gps_before_sample_id) REFERENCES gps_samples(id),
            FOREIGN KEY(gps_after_sample_id) REFERENCES gps_samples(id)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS incidents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            incident_key TEXT NOT NULL UNIQUE,
            category TEXT NOT NULL DEFAULT 'pothole',
            first_seen TEXT NOT NULL,
            last_seen TEXT NOT NULL,
            best_confidence REAL NOT NULL,
            latitude REAL,
            longitude REAL,
            location_accuracy_m REAL,
            location_source TEXT,
            is_simulated INTEGER,
            location_semantics TEXT NOT NULL DEFAULT 'vehicle_position_estimate',
            status TEXT NOT NULL DEFAULT 'needs_review',
            merge_method TEXT NOT NULL DEFAULT 'single_track',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS incident_tracks (
            incident_id INTEGER NOT NULL,
            pothole_track_id INTEGER NOT NULL UNIQUE,
            PRIMARY KEY(incident_id, pothole_track_id),
            FOREIGN KEY(incident_id) REFERENCES incidents(id) ON DELETE CASCADE,
            FOREIGN KEY(pothole_track_id) REFERENCES pothole_tracks(id) ON DELETE CASCADE
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS generated_reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            report_type TEXT NOT NULL,
            target_id INTEGER NOT NULL,
            model TEXT NOT NULL,
            prompt_version TEXT NOT NULL,
            evidence_json TEXT NOT NULL,
            report_json TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """)

    cursor.execute("CREATE INDEX IF NOT EXISTS idx_gps_samples_session_time ON gps_samples(session_id, elapsed_ms)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_observation_locations_session_time ON observation_locations(session_id, frame_elapsed_ms)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_incidents_location ON incidents(latitude, longitude)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_incidents_last_seen ON incidents(last_seen)")

    conn.commit()

    conn.close()