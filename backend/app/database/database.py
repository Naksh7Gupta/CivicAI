"""SQLite connection management and additive schema migrations."""
import sqlite3
from pathlib import Path

from app.core.config import DATABASE_PATH


def get_connection():
    DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DATABASE_PATH)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA foreign_keys=ON")
    return connection


def _ensure_column(cursor, table, column, declaration):
    columns = {row["name"] for row in cursor.execute(f"PRAGMA table_info({table})").fetchall()}
    if column not in columns:
        cursor.execute(f"ALTER TABLE {table} ADD COLUMN {column} {declaration}")


def initialize_database():
    connection = get_connection()
    cursor = connection.cursor()
    try:
        cursor.execute("""CREATE TABLE IF NOT EXISTS pothole_tracks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL, track_id INTEGER NOT NULL,
            first_seen TEXT NOT NULL, last_seen TEXT NOT NULL,
            best_confidence REAL NOT NULL,
            x1 INTEGER, y1 INTEGER, x2 INTEGER, y2 INTEGER,
            crop_path TEXT, image BLOB,
            image_mime TEXT NOT NULL DEFAULT 'image/jpeg',
            UNIQUE(session_id, track_id)
        )""")
        cursor.execute("""CREATE TABLE IF NOT EXISTS observations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            pothole_id INTEGER NOT NULL, timestamp TEXT NOT NULL,
            confidence REAL NOT NULL,
            x1 INTEGER, y1 INTEGER, x2 INTEGER, y2 INTEGER,
            FOREIGN KEY(pothole_id) REFERENCES pothole_tracks(id)
        )""")
        cursor.execute("""CREATE TABLE IF NOT EXISTS gps_fixes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL, recorded_at TEXT NOT NULL,
            latitude REAL NOT NULL CHECK(latitude BETWEEN -90 AND 90),
            longitude REAL NOT NULL CHECK(longitude BETWEEN -180 AND 180),
            accuracy_m REAL NOT NULL CHECK(accuracy_m > 0),
            source TEXT NOT NULL,
            is_simulated INTEGER NOT NULL DEFAULT 0 CHECK(is_simulated IN (0, 1)),
            UNIQUE(session_id, recorded_at)
        )""")
        cursor.execute("""CREATE TABLE IF NOT EXISTS incidents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL, track_id INTEGER NOT NULL,
            first_seen TEXT NOT NULL, last_seen TEXT NOT NULL,
            best_confidence REAL NOT NULL,
            observation_count INTEGER NOT NULL DEFAULT 0,
            reference_latitude REAL, reference_longitude REAL,
            gps_accuracy_m REAL, location_source TEXT,
            is_simulated INTEGER NOT NULL DEFAULT 0,
            location_basis TEXT,
            UNIQUE(session_id, track_id)
        )""")
        cursor.execute("""CREATE TABLE IF NOT EXISTS generated_reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            incident_id INTEGER, report_type TEXT NOT NULL,
            generated_at TEXT NOT NULL, model TEXT NOT NULL,
            context_json TEXT NOT NULL, narrative TEXT NOT NULL,
            FOREIGN KEY(incident_id) REFERENCES incidents(id)
        )""")

        # Additive migrations preserve existing track and observation records.
        _ensure_column(cursor, "pothole_tracks", "image", "BLOB")
        _ensure_column(cursor, "pothole_tracks", "image_mime", "TEXT NOT NULL DEFAULT 'image/jpeg'")
        _ensure_column(cursor, "pothole_tracks", "incident_id", "INTEGER REFERENCES incidents(id)")
        _ensure_column(cursor, "observations", "incident_id", "INTEGER REFERENCES incidents(id)")
        _ensure_column(cursor, "observations", "frame_timestamp", "TEXT")
        _ensure_column(cursor, "observations", "latitude", "REAL")
        _ensure_column(cursor, "observations", "longitude", "REAL")
        _ensure_column(cursor, "observations", "gps_accuracy_m", "REAL")
        _ensure_column(cursor, "observations", "location_source", "TEXT")
        _ensure_column(cursor, "observations", "is_simulated", "INTEGER NOT NULL DEFAULT 0")
        _ensure_column(cursor, "observations", "gps_association_method", "TEXT")
        _ensure_column(cursor, "observations", "gps_offset_ms", "REAL")
        _ensure_column(cursor, "observations", "gps_fix_before_id", "INTEGER REFERENCES gps_fixes(id)")
        _ensure_column(cursor, "observations", "gps_fix_after_id", "INTEGER REFERENCES gps_fixes(id)")

        cursor.execute("CREATE INDEX IF NOT EXISTS idx_gps_fixes_session_time ON gps_fixes(session_id, recorded_at)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_observations_incident ON observations(incident_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_incidents_last_seen ON incidents(last_seen)")

        for row in cursor.execute(
            "SELECT id, crop_path FROM pothole_tracks WHERE image IS NULL AND crop_path IS NOT NULL"
        ).fetchall():
            image_path = Path(row["crop_path"])
            if image_path.is_file():
                cursor.execute(
                    "UPDATE pothole_tracks SET image=?, image_mime='image/jpeg' WHERE id=?",
                    (image_path.read_bytes(), row["id"]),
                )
        connection.commit()
    finally:
        connection.close()
