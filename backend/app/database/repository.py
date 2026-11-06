"""Persistence operations for tracks, observations, and incident summaries."""
from app.database.database import get_connection


def _read_image(crop_path):
    if not crop_path:
        return None
    try:
        with open(crop_path, "rb") as image_file:
            return image_file.read()
    except OSError:
        return None


def _location_value(location, name, default=None):
    if location is None:
        return default
    if isinstance(location, dict):
        return location.get(name, default)
    return getattr(location, name, default)


def create_incident(session_id, timestamp, confidence, location=None):
    conn = get_connection()
    try:
        cursor = conn.execute(
            """
            INSERT INTO incidents (
                session_id, created_at, updated_at, first_seen, last_seen,
                best_confidence, observation_count, latitude, longitude,
                gps_accuracy_m, gps_delta_seconds, location_source,
                is_simulated, location_status
            ) VALUES (?, ?, ?, ?, ?, ?, 0, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                session_id,
                timestamp,
                timestamp,
                timestamp,
                timestamp,
                confidence,
                _location_value(location, "latitude"),
                _location_value(location, "longitude"),
                _location_value(location, "accuracy_m"),
                _location_value(location, "delta_seconds"),
                _location_value(location, "location_source"),
                None if location is None else int(_location_value(location, "is_simulated", False)),
                _location_value(location, "location_status", "unavailable"),
            ),
        )
        incident_id = cursor.lastrowid
        conn.commit()
        return incident_id
    finally:
        conn.close()


def create_track(session_id, track_id, timestamp, confidence, bbox, crop_path, incident_id):
    conn = get_connection()
    try:
        cursor = conn.execute(
            """
            INSERT INTO pothole_tracks (
                session_id, track_id, first_seen, last_seen, best_confidence,
                x1, y1, x2, y2, crop_path, image, image_mime, incident_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'image/jpeg', ?)
            """,
            (
                session_id,
                track_id,
                timestamp,
                timestamp,
                confidence,
                *bbox,
                crop_path,
                _read_image(crop_path),
                incident_id,
            ),
        )
        track_id_db = cursor.lastrowid
        conn.execute(
            "UPDATE incidents SET evidence_track_id = COALESCE(evidence_track_id, ?) WHERE id = ?",
            (track_id_db, incident_id),
        )
        conn.commit()
        return track_id_db
    finally:
        conn.close()


def get_track(session_id, track_id):
    conn = get_connection()
    try:
        return conn.execute(
            "SELECT * FROM pothole_tracks WHERE session_id = ? AND track_id = ?",
            (session_id, track_id),
        ).fetchone()
    finally:
        conn.close()


def update_track(pothole_id, timestamp, confidence, bbox, crop_path=None):
    conn = get_connection()
    try:
        if crop_path:
            conn.execute(
                """
                UPDATE pothole_tracks
                SET last_seen = ?, best_confidence = MAX(best_confidence, ?),
                    x1 = ?, y1 = ?, x2 = ?, y2 = ?, crop_path = ?,
                    image = ?, image_mime = 'image/jpeg'
                WHERE id = ?
                """,
                (timestamp, confidence, *bbox, crop_path, _read_image(crop_path), pothole_id),
            )
        else:
            conn.execute(
                """
                UPDATE pothole_tracks
                SET last_seen = ?, best_confidence = MAX(best_confidence, ?)
                WHERE id = ?
                """,
                (timestamp, confidence, pothole_id),
            )
        conn.commit()
    finally:
        conn.close()


def add_observation(
    pothole_id,
    timestamp,
    confidence,
    bbox,
    video_timestamp_seconds=None,
    timestamp_source=None,
    location=None,
):
    conn = get_connection()
    try:
        cursor = conn.execute(
            """
            INSERT INTO observations (
                pothole_id, timestamp, confidence, x1, y1, x2, y2,
                video_timestamp_seconds, timestamp_source, latitude, longitude,
                gps_accuracy_m, gps_delta_seconds, location_source, is_simulated,
                location_status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                pothole_id,
                timestamp,
                confidence,
                *bbox,
                video_timestamp_seconds,
                timestamp_source,
                _location_value(location, "latitude"),
                _location_value(location, "longitude"),
                _location_value(location, "accuracy_m"),
                _location_value(location, "delta_seconds"),
                _location_value(location, "location_source"),
                None if location is None else int(_location_value(location, "is_simulated", False)),
                _location_value(location, "location_status", "unavailable"),
            ),
        )
        observation_id = cursor.lastrowid
        conn.commit()
        return observation_id
    finally:
        conn.close()


def assign_track_incident(track_id, incident_id):
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE pothole_tracks SET incident_id = ? WHERE id = ?",
            (incident_id, track_id),
        )
        conn.commit()
    finally:
        conn.close()


def update_incident_after_observation(incident_id, timestamp, confidence, location=None):
    conn = get_connection()
    try:
        conn.execute(
            """
            UPDATE incidents
            SET updated_at = ?, last_seen = ?,
                best_confidence = MAX(best_confidence, ?),
                observation_count = observation_count + 1
            WHERE id = ?
            """,
            (timestamp, timestamp, confidence, incident_id),
        )
        if location is not None:
            current = conn.execute(
                "SELECT gps_accuracy_m, latitude FROM incidents WHERE id = ?",
                (incident_id,),
            ).fetchone()
            new_accuracy = _location_value(location, "accuracy_m")
            should_replace = current is not None and current["latitude"] is None
            if current is not None and current["latitude"] is not None:
                old_accuracy = current["gps_accuracy_m"]
                if old_accuracy is None and new_accuracy is not None:
                    should_replace = True
                elif old_accuracy is not None and new_accuracy is not None:
                    should_replace = new_accuracy < old_accuracy
            if should_replace:
                conn.execute(
                    """
                    UPDATE incidents SET latitude = ?, longitude = ?,
                        gps_accuracy_m = ?, gps_delta_seconds = ?,
                        location_source = ?, is_simulated = ?, location_status = ?
                    WHERE id = ?
                    """,
                    (
                        _location_value(location, "latitude"),
                        _location_value(location, "longitude"),
                        new_accuracy,
                        _location_value(location, "delta_seconds"),
                        _location_value(location, "location_source"),
                        int(_location_value(location, "is_simulated", False)),
                        _location_value(location, "location_status", "unavailable"),
                        incident_id,
                    ),
                )
        conn.commit()
    finally:
        conn.close()


def list_incidents(session_id=None):
    conn = get_connection()
    try:
        if session_id:
            rows = conn.execute(
                "SELECT * FROM incidents WHERE session_id = ? ORDER BY last_seen DESC",
                (session_id,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM incidents ORDER BY last_seen DESC"
            ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def get_incident_report_context(incident_id):
    conn = get_connection()
    try:
        incident = conn.execute(
            "SELECT * FROM incidents WHERE id = ?",
            (incident_id,),
        ).fetchone()
        if incident is None:
            return None
        tracks = conn.execute(
            """
            SELECT id, track_id, first_seen, last_seen, best_confidence,
                   CASE WHEN image IS NULL THEN 0 ELSE 1 END AS has_evidence
            FROM pothole_tracks WHERE incident_id = ? ORDER BY id
            """,
            (incident_id,),
        ).fetchall()
        observation_stats = conn.execute(
            """
            SELECT COUNT(*) AS count, AVG(o.confidence) AS average_confidence,
                   MIN(o.video_timestamp_seconds) AS first_video_second,
                   MAX(o.video_timestamp_seconds) AS last_video_second,
                   SUM(CASE WHEN o.latitude IS NOT NULL AND o.longitude IS NOT NULL THEN 1 ELSE 0 END) AS located_observations
            FROM observations o
            JOIN pothole_tracks t ON t.id = o.pothole_id
            WHERE t.incident_id = ?
            """,
            (incident_id,),
        ).fetchone()
        result = dict(incident)
        result["tracks"] = [
            {
                **dict(row),
                "evidence_url": f"/api/potholes/{row['id']}/image" if row["has_evidence"] else None,
            }
            for row in tracks
        ]
        result["observation_stats"] = dict(observation_stats)
        result["track_count"] = len(tracks)
        result["evidence_count"] = sum(row["has_evidence"] for row in tracks)
        result["timestamp_semantics"] = {
            "first_seen_last_seen": "UTC database ingestion/processing timestamps, not original camera capture time",
            "video_timestamp_seconds": "relative media timeline seconds from the start of the video",
        }
        result["is_simulated"] = (
            None if result["is_simulated"] is None else bool(result["is_simulated"])
        )
        return result
    finally:
        conn.close()


def get_area_report_context(session_id=None):
    conn = get_connection()
    try:
        where = "WHERE session_id = ?" if session_id else ""
        params = (session_id,) if session_id else ()
        totals = conn.execute(
            f"""
            SELECT COUNT(*) AS incident_count,
                   COALESCE(SUM(observation_count), 0) AS observation_count,
                   AVG(best_confidence) AS average_best_confidence,
                   SUM(CASE WHEN latitude IS NOT NULL AND longitude IS NOT NULL THEN 1 ELSE 0 END) AS located_incident_count,
                   SUM(CASE WHEN is_simulated = 1 THEN 1 ELSE 0 END) AS simulated_location_count
            FROM incidents {where}
            """,
            params,
        ).fetchone()
        if session_id:
            evidence = conn.execute(
                """
                SELECT COUNT(*) FROM pothole_tracks t
                JOIN incidents i ON i.id = t.incident_id
                WHERE i.session_id = ? AND t.image IS NOT NULL
                """,
                (session_id,),
            ).fetchone()[0]
        else:
            evidence = conn.execute(
                "SELECT COUNT(*) FROM pothole_tracks WHERE image IS NOT NULL"
            ).fetchone()[0]
        sample_sql = f"SELECT id, first_seen, last_seen, best_confidence, observation_count, latitude, longitude, location_source, is_simulated, location_status FROM incidents {where} ORDER BY last_seen DESC LIMIT 25"
        samples = conn.execute(sample_sql, params).fetchall()
        result = dict(totals)
        result["session_id"] = session_id
        result["evidence_count"] = evidence
        result["sample_incidents"] = [dict(row) for row in samples]
        return result
    finally:
        conn.close()
