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
    conn.execute("PRAGMA busy_timeout=5000")

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

    # Backwards-compatible GPS fields on each frame observation.
    observation_columns = {
        row["name"]
        for row in cursor.execute("PRAGMA table_info(observations)").fetchall()
    }
    gps_columns = {
        "video_time_ms": "REAL",
        "latitude": "REAL",
        "longitude": "REAL",
        "gps_accuracy_m": "REAL",
        "location_source": "TEXT",
        "is_simulated": "INTEGER NOT NULL DEFAULT 0",
        "gps_association_method": "TEXT",
        "gps_association_reason": "TEXT",
        "gps_time_delta_ms": "REAL",
    }
    for name, definition in gps_columns.items():
        if name not in observation_columns:
            cursor.execute(f"ALTER TABLE observations ADD COLUMN {name} {definition}")

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS gps_samples (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            video_time_ms REAL NOT NULL,
            latitude REAL NOT NULL,
            longitude REAL NOT NULL,
            accuracy_m REAL,
            source TEXT NOT NULL CHECK(source IN ('real', 'synthetic')),
            is_simulated INTEGER NOT NULL CHECK(is_simulated IN (0, 1)),
            captured_at_utc TEXT,
            UNIQUE(session_id, video_time_ms)
        )
    """)
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_gps_samples_session_time "
        "ON gps_samples(session_id, video_time_ms)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_observations_track_time "
        "ON observations(pothole_id, timestamp)"
    )

    conn.commit()

    conn.close()