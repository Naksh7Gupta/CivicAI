"""Read-side aggregation: one incident per tracker track within a session."""
from app.database.database import get_connection


_INCIDENT_SELECT = """
SELECT
    p.id AS track_record_id, p.session_id, p.track_id,
    p.first_seen, p.last_seen, p.best_confidence,
    COUNT(o.id) AS observation_count,
    SUM(CASE WHEN o.latitude IS NOT NULL AND o.longitude IS NOT NULL THEN 1 ELSE 0 END)
        AS located_observation_count,
    best.latitude, best.longitude, best.gps_accuracy_m,
    best.location_source, best.is_simulated, best.gps_association_method,
    p.image IS NOT NULL AS has_image
FROM pothole_tracks AS p
LEFT JOIN observations AS o ON o.pothole_id = p.id
LEFT JOIN observations AS best ON best.id = (
    SELECT candidate.id
    FROM observations AS candidate
    WHERE candidate.pothole_id = p.id
      AND candidate.latitude IS NOT NULL
      AND candidate.longitude IS NOT NULL
    ORDER BY
      CASE WHEN candidate.gps_accuracy_m IS NULL THEN 1 ELSE 0 END,
      candidate.gps_accuracy_m ASC,
      candidate.timestamp DESC
    LIMIT 1
)
"""


def _to_incident(row) -> dict:
    located = row["latitude"] is not None and row["longitude"] is not None
    return {
        "id": f"PH-{row['track_record_id']:04d}",
        "track_record_id": row["track_record_id"],
        "session_id": row["session_id"],
        "tracker_id": row["track_id"],
        "issue_category": "pothole_candidate",
        "first_seen": row["first_seen"],
        "last_seen": row["last_seen"],
        "timestamp_semantics": "UTC processing time; source-video capture time is not available",
        "best_detection_confidence": row["best_confidence"],
        "observation_count": row["observation_count"] or 0,
        "located_observation_count": row["located_observation_count"] or 0,
        "latitude": row["latitude"],
        "longitude": row["longitude"],
        "gps_accuracy_m": row["gps_accuracy_m"],
        "location_source": row["location_source"],
        "is_simulated": bool(row["is_simulated"]) if located else False,
        "location_kind": "vehicle_position_estimate" if located else None,
        "gps_association_method": row["gps_association_method"],
        "severity": "not_assessed",
        "status": "needs_review",
        "has_image": bool(row["has_image"]),
        "image_url": f"/api/potholes/{row['track_record_id']}/image" if row["has_image"] else None,
        "deduplication_scope": "same_session_tracker_track",
        "cross_session_deduplication": "not_performed",
    }


def list_incidents(session_id: str | None = None) -> list[dict]:
    sql, params = _INCIDENT_SELECT, []
    if session_id:
        sql += " WHERE p.session_id = ?"
        params.append(session_id)
    sql += " GROUP BY p.id ORDER BY p.last_seen DESC"
    conn = get_connection()
    try:
        return [_to_incident(row) for row in conn.execute(sql, params).fetchall()]
    finally:
        conn.close()


def get_incident_evidence(track_record_id: int) -> dict | None:
    conn = get_connection()
    try:
        row = conn.execute(
            _INCIDENT_SELECT + " WHERE p.id = ? GROUP BY p.id",
            (track_record_id,),
        ).fetchone()
        if row is None:
            return None
        incident = _to_incident(row)
        observations = conn.execute(
            """
            SELECT id, timestamp, video_time_ms, confidence, latitude, longitude,
                   gps_accuracy_m, location_source, is_simulated,
                   gps_association_method, gps_association_reason
            FROM observations WHERE pothole_id = ? ORDER BY timestamp, id
            """,
            (track_record_id,),
        ).fetchall()
        incident["evidence"] = [
            {
                "observation_id": f"OBS-{item['id']}",
                "timestamp": item["timestamp"],
                "timestamp_semantics": "UTC processing time",
                "video_time_ms": item["video_time_ms"],
                "detection_confidence": item["confidence"],
                "gps_associated": item["latitude"] is not None and item["longitude"] is not None,
                "latitude": item["latitude"],
                "longitude": item["longitude"],
                "gps_accuracy_m": item["gps_accuracy_m"],
                "location_source": item["location_source"],
                "is_simulated": bool(item["is_simulated"]),
                "gps_association_method": item["gps_association_method"],
                "gps_association_reason": item["gps_association_reason"],
            }
            for item in observations
        ]
        return incident
    finally:
        conn.close()
