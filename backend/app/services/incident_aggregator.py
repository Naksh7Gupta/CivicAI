"""Tracker-level incident aggregation.

Automatic merging is deliberately limited to one tracker ID in one recording
session. Camera GPS is not a surveyed defect position and is not used to merge
incidents across separate recording sessions.
"""
from app.database.database import get_connection


def create_incident(session_id, track_id, timestamp, confidence, gps_association=None):
    gps = gps_association
    connection = get_connection()
    try:
        connection.execute(
            """INSERT OR IGNORE INTO incidents (
                 session_id, track_id, first_seen, last_seen, best_confidence,
                 observation_count, reference_latitude, reference_longitude,
                 gps_accuracy_m, location_source, is_simulated, location_basis
               ) VALUES (?, ?, ?, ?, ?, 0, ?, ?, ?, ?, ?, ?)""",
            (session_id, track_id, timestamp, timestamp, confidence,
             gps.latitude if gps else None, gps.longitude if gps else None,
             gps.accuracy_m if gps else None, gps.source if gps else None,
             int(gps.is_simulated) if gps else 0,
             "camera_position_estimate" if gps else None),
        )
        row = connection.execute(
            "SELECT id FROM incidents WHERE session_id=? AND track_id=?",
            (session_id, track_id),
        ).fetchone()
        connection.commit()
        return int(row["id"])
    finally:
        connection.close()


def record_incident_observation(incident_id, timestamp, confidence, gps_association=None):
    connection = get_connection()
    try:
        if gps_association is None:
            connection.execute(
                """UPDATE incidents SET last_seen=?, best_confidence=MAX(best_confidence, ?),
                   observation_count=observation_count+1 WHERE id=?""",
                (timestamp, confidence, incident_id),
            )
        else:
            gps = gps_association
            connection.execute(
                """UPDATE incidents SET
                     last_seen=?, best_confidence=MAX(best_confidence, ?),
                     observation_count=observation_count+1,
                     reference_latitude=CASE WHEN gps_accuracy_m IS NULL OR gps_accuracy_m>? THEN ? ELSE reference_latitude END,
                     reference_longitude=CASE WHEN gps_accuracy_m IS NULL OR gps_accuracy_m>? THEN ? ELSE reference_longitude END,
                     gps_accuracy_m=CASE WHEN gps_accuracy_m IS NULL OR gps_accuracy_m>? THEN ? ELSE gps_accuracy_m END,
                     location_source=CASE WHEN gps_accuracy_m IS NULL OR gps_accuracy_m>? THEN ? ELSE location_source END,
                     is_simulated=CASE WHEN gps_accuracy_m IS NULL OR gps_accuracy_m>? THEN ? ELSE is_simulated END,
                     location_basis='camera_position_estimate'
                   WHERE id=?""",
                (timestamp, confidence,
                 gps.accuracy_m, gps.latitude,
                 gps.accuracy_m, gps.longitude,
                 gps.accuracy_m, gps.accuracy_m,
                 gps.accuracy_m, gps.source,
                 gps.accuracy_m, int(gps.is_simulated), incident_id),
            )
        connection.commit()
    finally:
        connection.close()
