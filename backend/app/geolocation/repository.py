"""Database operations for timestamped GPS fixes."""
from app.database.database import get_connection
from app.geolocation.association import GPSFix, associate_gps_fixes, parse_timestamp


def save_gps_fix(session_id, recorded_at, latitude, longitude, accuracy_m, *, source="gps", is_simulated=False):
    if not session_id:
        raise ValueError("session_id is required")
    fix = GPSFix(parse_timestamp(recorded_at), latitude, longitude, accuracy_m, source, is_simulated).validated()
    connection = get_connection()
    try:
        connection.execute(
            """INSERT INTO gps_fixes
               (session_id, recorded_at, latitude, longitude, accuracy_m, source, is_simulated)
               VALUES (?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(session_id, recorded_at) DO UPDATE SET
                 latitude=excluded.latitude, longitude=excluded.longitude,
                 accuracy_m=excluded.accuracy_m, source=excluded.source,
                 is_simulated=excluded.is_simulated""",
            (session_id, fix.recorded_at.isoformat(), fix.latitude, fix.longitude,
             fix.accuracy_m, fix.source, int(fix.is_simulated)),
        )
        row = connection.execute(
            "SELECT id FROM gps_fixes WHERE session_id=? AND recorded_at=?",
            (session_id, fix.recorded_at.isoformat()),
        ).fetchone()
        connection.commit()
        return int(row["id"])
    finally:
        connection.close()


def associate_session_fix(session_id, frame_timestamp, *, max_gap_seconds=2.0, max_accuracy_m=15.0):
    if frame_timestamp is None:
        return None
    target = parse_timestamp(frame_timestamp).isoformat()
    connection = get_connection()
    try:
        before = connection.execute(
            """SELECT * FROM gps_fixes WHERE session_id=? AND recorded_at<=? AND accuracy_m<=?
               ORDER BY recorded_at DESC LIMIT 1""", (session_id, target, max_accuracy_m)
        ).fetchone()
        after = connection.execute(
            """SELECT * FROM gps_fixes WHERE session_id=? AND recorded_at>=? AND accuracy_m<=?
               ORDER BY recorded_at ASC LIMIT 1""", (session_id, target, max_accuracy_m)
        ).fetchone()
        rows = [row for row in (before, after) if row is not None]
        if len(rows) == 2 and rows[0]["id"] == rows[1]["id"]:
            rows.pop()
        fixes = [
            GPSFix(parse_timestamp(row["recorded_at"]), row["latitude"], row["longitude"],
                   row["accuracy_m"], row["source"], bool(row["is_simulated"]), row["id"])
            for row in rows
        ]
    finally:
        connection.close()
    return associate_gps_fixes(fixes, target, max_gap_seconds=max_gap_seconds,
                               max_accuracy_m=max_accuracy_m)
