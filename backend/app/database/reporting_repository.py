"""Persistence helpers for GPS samples and frame-location associations."""
from app.database.database import get_connection


def save_gps_samples(session_id, samples):
    connection = get_connection()
    try:
        connection.executemany(
            """
            INSERT OR IGNORE INTO gps_samples (
                session_id, sample_index, elapsed_ms, latitude, longitude,
                accuracy_m, source, is_simulated
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    session_id,
                    sample.sample_index,
                    sample.elapsed_ms,
                    sample.latitude,
                    sample.longitude,
                    sample.accuracy_m,
                    sample.source,
                    int(sample.is_simulated),
                )
                for sample in samples
            ],
        )
        connection.commit()
    finally:
        connection.close()


def save_observation_location(session_id, observation_id, frame_elapsed_ms, match):
    connection = get_connection()
    try:
        before = connection.execute(
            "SELECT id FROM gps_samples WHERE session_id = ? AND sample_index = ?",
            (session_id, match.before_sample_index),
        ).fetchone()
        after = connection.execute(
            "SELECT id FROM gps_samples WHERE session_id = ? AND sample_index = ?",
            (session_id, match.after_sample_index),
        ).fetchone()
        if before is None or after is None:
            raise ValueError("Matched GPS sample was not persisted for this session.")

        connection.execute(
            """
            INSERT OR REPLACE INTO observation_locations (
                observation_id, session_id, frame_elapsed_ms,
                latitude, longitude, accuracy_m, location_source,
                is_simulated, method, gps_before_sample_id,
                gps_after_sample_id, time_delta_ms, location_semantics
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                observation_id,
                session_id,
                frame_elapsed_ms,
                match.latitude,
                match.longitude,
                match.accuracy_m,
                match.source,
                int(match.is_simulated),
                match.method,
                before["id"],
                after["id"],
                match.time_delta_ms,
                "vehicle_position_estimate",
            ),
        )
        connection.commit()
    finally:
        connection.close()
