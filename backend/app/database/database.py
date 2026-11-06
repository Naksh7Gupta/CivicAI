"""SQLite connection management and backwards-compatible schema migrations."""
import sqlite3
from pathlib import Path

from app.core.config import DATABASE_PATH


def get_connection():
    DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def _add_missing_columns(cursor, table_name, definitions):
    columns = {
        row["name"]
        for row in cursor.execute(f"PRAGMA table_info({table_name})").fetchall()
    }
    for name, definition in definitions.items():
        if name not in columns:
            cursor.execute(f"ALTER TABLE {table_name} ADD COLUMN {name} {definition}")


def initialize_database():
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS incidents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                first_seen TEXT NOT NULL,
                last_seen TEXT NOT NULL,
                best_confidence REAL NOT NULL,
                observation_count INTEGER NOT NULL DEFAULT 0,
                latitude REAL,
                longitude REAL,
                gps_accuracy_m REAL,
                gps_delta_seconds REAL,
                location_source TEXT,
                is_simulated INTEGER,
                location_status TEXT NOT NULL DEFAULT 'unavailable',
                evidence_track_id INTEGER
            )
        """)

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
                incident_id INTEGER REFERENCES incidents(id),
                UNIQUE(session_id, track_id)
            )
        """)
        _add_missing_columns(
            cursor,
            "pothole_tracks",
            {
                "image": "BLOB",
                "image_mime": "TEXT NOT NULL DEFAULT 'image/jpeg'",
                "incident_id": "INTEGER REFERENCES incidents(id)",
            },
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
                video_timestamp_seconds REAL,
                timestamp_source TEXT,
                latitude REAL,
                longitude REAL,
                gps_accuracy_m REAL,
                gps_delta_seconds REAL,
                location_source TEXT,
                is_simulated INTEGER,
                location_status TEXT NOT NULL DEFAULT 'unavailable',
                FOREIGN KEY(pothole_id) REFERENCES pothole_tracks(id)
            )
        """)
        _add_missing_columns(
            cursor,
            "observations",
            {
                "video_timestamp_seconds": "REAL",
                "timestamp_source": "TEXT",
                "latitude": "REAL",
                "longitude": "REAL",
                "gps_accuracy_m": "REAL",
                "gps_delta_seconds": "REAL",
                "location_source": "TEXT",
                "is_simulated": "INTEGER",
                "location_status": "TEXT NOT NULL DEFAULT 'unavailable'",
            },
        )

        # Preserve existing databases: old tracks become one incident each.
        legacy_tracks = cursor.execute(
            "SELECT * FROM pothole_tracks WHERE incident_id IS NULL"
        ).fetchall()
        for track in legacy_tracks:
            observation_count = cursor.execute(
                "SELECT COUNT(*) FROM observations WHERE pothole_id = ?",
                (track["id"],),
            ).fetchone()[0]
            cursor.execute(
                """
                INSERT INTO incidents (
                    session_id, created_at, updated_at, first_seen, last_seen,
                    best_confidence, observation_count, location_status, evidence_track_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 'unavailable', ?)
                """,
                (
                    track["session_id"],
                    track["first_seen"],
                    track["last_seen"],
                    track["first_seen"],
                    track["last_seen"],
                    track["best_confidence"],
                    observation_count,
                    track["id"],
                ),
            )
            cursor.execute(
                "UPDATE pothole_tracks SET incident_id = ? WHERE id = ?",
                (cursor.lastrowid, track["id"]),
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

        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_tracks_incident_id ON pothole_tracks(incident_id)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_observations_track_time ON observations(pothole_id, timestamp)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_incidents_session_time ON incidents(session_id, last_seen)"
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
