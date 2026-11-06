"""Persistence and backfilling for timestamp-aligned GPS samples."""
from app.database.database import get_connection
from app.services.gps_association import GPSAssociation, GPSSample, associate_position


def save_gps_samples(session_id: str, samples: list[dict]) -> int:
    if not session_id.strip():
        raise ValueError("session_id is required.")
    validated = [GPSSample.from_mapping(sample) for sample in samples]
    if not validated:
        return 0

    conn = get_connection()
    try:
        conn.executemany(
            """
            INSERT INTO gps_samples (
                session_id, video_time_ms, latitude, longitude, accuracy_m,
                source, is_simulated, captured_at_utc
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(session_id, video_time_ms) DO UPDATE SET
                latitude = excluded.latitude,
                longitude = excluded.longitude,
                accuracy_m = excluded.accuracy_m,
                source = excluded.source,
                is_simulated = excluded.is_simulated,
                captured_at_utc = excluded.captured_at_utc
            """,
            [
                (
                    session_id, sample.video_time_ms, sample.latitude, sample.longitude,
                    sample.accuracy_m, sample.source, int(sample.is_simulated),
                    sample_data.get("captured_at_utc"),
                )
                for sample, sample_data in zip(validated, samples)
            ],
        )
        conn.commit()
        return len(validated)
    finally:
        conn.close()


def _load_samples(conn, session_id: str) -> list[GPSSample]:
    rows = conn.execute(
        "SELECT video_time_ms, latitude, longitude, accuracy_m, source, is_simulated "
        "FROM gps_samples WHERE session_id = ? ORDER BY video_time_ms",
        (session_id,),
    ).fetchall()
    return [
        GPSSample.from_mapping({
            "video_time_ms": row["video_time_ms"],
            "latitude": row["latitude"],
            "longitude": row["longitude"],
            "accuracy_m": row["accuracy_m"],
            "source": row["source"],
            "is_simulated": bool(row["is_simulated"]),
        })
        for row in rows
    ]


def _write_association(conn, observation_id: int, association) -> None:
    conn.execute(
        """
        UPDATE observations
        SET latitude = ?, longitude = ?, gps_accuracy_m = ?,
            location_source = ?, is_simulated = ?,
            gps_association_method = ?, gps_association_reason = ?,
            gps_time_delta_ms = ?
        WHERE id = ?
        """,
        (
            association.latitude, association.longitude, association.accuracy_m,
            association.source, int(association.is_simulated), association.method,
            association.reason, association.time_delta_ms, observation_id,
        ),
    )


def associate_observation(observation_id: int, session_id: str, video_time_ms: float) -> dict:
    conn = get_connection()
    try:
        samples = _load_samples(conn, session_id)
        association = associate_position(video_time_ms, samples)
        _write_association(conn, observation_id, association)
        conn.commit()
        return association.to_dict()
    finally:
        conn.close()


def associate_session_observations(session_id: str) -> dict:
    """Re-associate timestamped observations after a GPS sidecar upload."""
    conn = get_connection()
    try:
        samples = _load_samples(conn, session_id)
        rows = conn.execute(
            """
            SELECT o.id, o.video_time_ms
            FROM observations AS o
            JOIN pothole_tracks AS p ON p.id = o.pothole_id
            WHERE p.session_id = ?
            ORDER BY o.video_time_ms, o.id
            """,
            (session_id,),
        ).fetchall()
        associated_count = 0
        for row in rows:
            if row["video_time_ms"] is None:
                association = GPSAssociation(
                    status="unavailable", reason="video_timestamp_unavailable"
                )
            else:
                association = associate_position(row["video_time_ms"], samples)
            if association.status == "associated":
                associated_count += 1
            _write_association(conn, row["id"], association)
        conn.commit()
        processed = len(rows)
        return {
            "observations_processed": processed,
            "observations_associated": associated_count,
            "observations_unavailable": processed - associated_count,
        }
    finally:
        conn.close()
