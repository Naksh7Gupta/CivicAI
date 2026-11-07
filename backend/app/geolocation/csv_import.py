"""Import GPS CSV columns: recorded_at, latitude, longitude, accuracy_m."""
import csv
from pathlib import Path

from app.geolocation.repository import save_gps_fix

_REQUIRED = {"recorded_at", "latitude", "longitude", "accuracy_m"}


def import_gps_csv(session_id, csv_path, *, source, is_simulated):
    imported = 0
    with Path(csv_path).open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        missing = _REQUIRED - set(reader.fieldnames or [])
        if missing:
            raise ValueError("GPS CSV is missing columns: " + ", ".join(sorted(missing)))
        for line_number, row in enumerate(reader, start=2):
            try:
                save_gps_fix(session_id, row["recorded_at"], float(row["latitude"]),
                             float(row["longitude"]), float(row["accuracy_m"]),
                             source=source, is_simulated=is_simulated)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"Invalid GPS data on CSV line {line_number}: {exc}") from exc
            imported += 1
    return imported
