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
        connection.execute(
            """UPDATE incidents SET
                 last_seen=?, best_confidence=MAX(best_confidence, ?),
                 observation_count=observation_count+1
               WHERE id=?""",
            (timestamp, confidence, incident_id),
        )

        if gps_association is not None:
            gps = gps_association
            current = connection.execute(
                "SELECT gps_accuracy_m, is_simulated FROM incidents WHERE id=?",
                (incident_id,),
            ).fetchone()
            if current is None:
                raise KeyError(f"Incident {incident_id} was not found")

            current_accuracy = current["gps_accuracy_m"]
            current_is_simulated = bool(current["is_simulated"])
            # A real GPS fix takes precedence over a simulated point even when
            # its reported accuracy is numerically larger. Within the same
            # simulation class, retain the fix with the smaller reported error.
            prefer_new_location = (
                current_accuracy is None
                or (current_is_simulated and not gps.is_simulated)
                or (
                    current_is_simulated == gps.is_simulated
                    and gps.accuracy_m < current_accuracy
                )
            )
            if prefer_new_location:
                connection.execute(
                    """UPDATE incidents SET
                         reference_latitude=?, reference_longitude=?,
                         gps_accuracy_m=?, location_source=?, is_simulated=?,
                         location_basis='camera_position_estimate'
                       WHERE id=?""",
                    (gps.latitude, gps.longitude, gps.accuracy_m, gps.source,
                     int(gps.is_simulated), incident_id),
                )
        connection.commit()
    finally:
        connection.close()
