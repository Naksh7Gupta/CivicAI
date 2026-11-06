"""Database repositories."""
from app.database.database import get_connection


def _read_image(crop_path):
    if not crop_path:
        return None
    with open(crop_path, "rb") as image_file:
        return image_file.read()


def create_track(
    session_id,
    track_id,
    timestamp,
    confidence,
    bbox,
    crop_path,
    image=None,
):
    image_blob = image if image is not None else _read_image(crop_path)
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO pothole_tracks (
                session_id, track_id, first_seen, last_seen, best_confidence,
                x1, y1, x2, y2, crop_path, image, image_mime
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'image/jpeg')
        """, (
            session_id,
            track_id,
            timestamp,
            timestamp,
            confidence,
            *bbox,
            crop_path,
            image_blob,
        ))
        pothole_id = cursor.lastrowid
        conn.commit()
        return pothole_id
    finally:
        conn.close()

def get_track(session_id, track_id):

    conn = get_connection()

    cursor = conn.cursor()

    cursor.execute("""
        SELECT *
        FROM pothole_tracks
        WHERE session_id = ?
        AND track_id = ?
    """, (session_id, track_id))

    result = cursor.fetchone()

    conn.close()

    return result


def update_track(
    pothole_id,
    timestamp,
    confidence,
    bbox,
    crop_path=None
):

    conn = get_connection()

    cursor = conn.cursor()

    if crop_path:

        cursor.execute("""
            UPDATE pothole_tracks

            SET
                last_seen = ?,
                best_confidence = ?,
                x1 = ?,
                y1 = ?,
                x2 = ?,
                y2 = ?,
                crop_path = ?,
                image = ?,
                image_mime = 'image/jpeg'

            WHERE id = ?

        """, (
            timestamp,
            confidence,
            *bbox,
            crop_path,
            _read_image(crop_path),
            pothole_id
        ))

    else:

        cursor.execute("""
            UPDATE pothole_tracks

            SET last_seen = ?

            WHERE id = ?

        """, (timestamp, pothole_id))

    conn.commit()

    conn.close()


def add_observation(
    pothole_id,
    timestamp,
    confidence,
    bbox
):
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO observations (
                pothole_id, timestamp, confidence, x1, y1, x2, y2
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            pothole_id,
            timestamp,
            confidence,
            *bbox
        ))
        observation_id = cursor.lastrowid
        conn.commit()
        return observation_id
    finally:
        conn.close()
