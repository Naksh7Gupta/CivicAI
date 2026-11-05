"""Database connection management."""
import sqlite3

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

            UNIQUE(session_id, track_id)
        )
    """)

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

    conn.commit()

    conn.close()