"""Persistence helpers for tracked potholes and frame observations."""
from app.database.database import get_connection


def _read_image(crop_path):
    if not crop_path:
        return None
    with open(crop_path, "rb") as image_file:
        return image_file.read()


def create_track(session_id, track_id, timestamp, confidence, bbox, crop_path, incident_id=None):
    connection = get_connection()
    try:
        cursor = connection.execute(
            """INSERT INTO pothole_tracks (
                 session_id, track_id, first_seen, last_seen, best_confidence,
                 x1, y1, x2, y2, crop_path, image, image_mime, incident_id
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'image/jpeg', ?)""",
            (session_id, track_id, timestamp, timestamp, confidence,
             *bbox, crop_path, _read_image(crop_path), incident_id),
        )
        connection.commit()
        return int(cursor.lastrowid)
    finally:
        connection.close()


def get_track(session_id, track_id):
    connection = get_connection()
    try:
        return connection.execute(
            "SELECT * FROM pothole_tracks WHERE session_id=? AND track_id=?",
            (session_id, track_id),
        ).fetchone()
    finally:
        connection.close()


def link_track_to_incident(pothole_id, incident_id):
    connection = get_connection()
    try:
        connection.execute("UPDATE pothole_tracks SET incident_id=? WHERE id=?",
                           (incident_id, pothole_id))
        connection.execute(
            "UPDATE observations SET incident_id=? WHERE pothole_id=? AND incident_id IS NULL",
            (incident_id, pothole_id),
        )
        connection.execute(
            """UPDATE incidents SET
                 observation_count=(SELECT COUNT(*) FROM observations WHERE incident_id=?),
                 first_seen=COALESCE((SELECT MIN(timestamp) FROM observations WHERE incident_id=?), first_seen),
                 last_seen=COALESCE((SELECT MAX(timestamp) FROM observations WHERE incident_id=?), last_seen),
                 best_confidence=MAX(best_confidence, COALESCE(
                   (SELECT MAX(confidence) FROM observations WHERE incident_id=?), best_confidence))
               WHERE id=?""",
            (incident_id, incident_id, incident_id, incident_id),
        )
        connection.commit()
    finally:
        connection.close()


def update_track(pothole_id, timestamp, confidence, bbox, crop_path=None):
    connection = get_connection()
    try:
        if crop_path:
            connection.execute(
                """UPDATE pothole_tracks SET
                     last_seen=?, best_confidence=MAX(best_confidence, ?),
                     x1=?, y1=?, x2=?, y2=?, crop_path=?, image=?, image_mime='image/jpeg'
                   WHERE id=?""",
                (timestamp, confidence, *bbox, crop_path, _read_image(crop_path), pothole_id),
            )
        else:
            connection.execute(
                """UPDATE pothole_tracks SET last_seen=?,
                   best_confidence=MAX(best_confidence, ?) WHERE id=?""",
                (timestamp, confidence, pothole_id),
            )
        connection.commit()
    finally:
        connection.close()


def add_observation(pothole_id, timestamp, confidence, bbox, *, incident_id=None,
                    frame_timestamp=None, gps_association=None):
    gps = gps_association
    connection = get_connection()
    try:
        connection.execute(
            """INSERT INTO observations (
                 pothole_id, timestamp, confidence, x1, y1, x2, y2,
                 incident_id, frame_timestamp, latitude, longitude,
                 gps_accuracy_m, location_source, is_simulated,
                 gps_association_method, gps_offset_ms,
                 gps_fix_before_id, gps_fix_after_id
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (pothole_id, timestamp, confidence, *bbox, incident_id, frame_timestamp,
             gps.latitude if gps else None, gps.longitude if gps else None,
             gps.accuracy_m if gps else None, gps.source if gps else None,
             int(gps.is_simulated) if gps else 0, gps.method if gps else None,
             gps.offset_ms if gps else None, gps.fix_before_id if gps else None,
             gps.fix_after_id if gps else None),
        )
        connection.commit()
    finally:
        connection.close()
