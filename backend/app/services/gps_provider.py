"""Timestamp-aware GPS association for recorded video.

The provider only associates coordinates supplied in a CSV. It never creates
or guesses coordinates. A fix is accepted only inside the configured time
window, and its source/simulation flag are carried into the database.
"""
from __future__ import annotations

import csv
import math
from bisect import bisect_left
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


@dataclass(frozen=True)
class LocationFix:
    video_timestamp_seconds: float
    latitude: float
    longitude: float
    accuracy_m: float | None
    location_source: str
    is_simulated: bool
    timestamp_utc: str | None = None


@dataclass(frozen=True)
class LocationMatch:
    latitude: float
    longitude: float
    accuracy_m: float | None
    delta_seconds: float
    location_source: str
    is_simulated: bool
    location_status: str
    sample_timestamp_seconds: float


def _parse_utc(value: str) -> datetime:
    normalized = value.strip()
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        raise ValueError("UTC timestamps must include a timezone offset or Z.")
    return parsed.astimezone(timezone.utc)


def _parse_bool(value: str) -> bool:
    normalized = value.strip().lower()
    if normalized in {"true", "1", "yes"}:
        return True
    if normalized in {"false", "0", "no"}:
        return False
    raise ValueError("is_simulated must be an explicit true/false value.")


class GPSLocationProvider:
    """Load timestamped location fixes and match frames to the nearest fix."""

    def __init__(
        self,
        fixes: list[LocationFix],
        *,
        max_delta_seconds: float = 2.0,
        max_accuracy_m: float = 50.0,
    ) -> None:
        if max_delta_seconds <= 0:
            raise ValueError("max_delta_seconds must be greater than zero.")
        if max_accuracy_m <= 0:
            raise ValueError("max_accuracy_m must be greater than zero.")
        if not fixes:
            raise ValueError("The GPS track contains no location samples.")
        ordered = sorted(fixes, key=lambda fix: fix.video_timestamp_seconds)
        timestamps = [fix.video_timestamp_seconds for fix in ordered]
        if len(timestamps) != len(set(timestamps)):
            raise ValueError("GPS track contains duplicate video timestamps.")
        self.fixes = ordered
        self.timestamps = timestamps
        self.max_delta_seconds = max_delta_seconds
        self.max_accuracy_m = max_accuracy_m

    @classmethod
    def from_csv(
        cls,
        path: str | Path,
        *,
        video_start_time_utc: str | None = None,
        max_delta_seconds: float = 2.0,
        max_accuracy_m: float = 50.0,
    ) -> "GPSLocationProvider":
        csv_path = Path(path)
        if not csv_path.is_file():
            raise FileNotFoundError(f"GPS track CSV was not found: {csv_path}")

        start_time = _parse_utc(video_start_time_utc) if video_start_time_utc else None
        fixes: list[LocationFix] = []
        with csv_path.open("r", encoding="utf-8-sig", newline="") as source:
            reader = csv.DictReader(source)
            headers = set(reader.fieldnames or [])
            required = {"latitude", "longitude", "location_source", "is_simulated"}
            missing = required - headers
            if missing:
                raise ValueError(
                    "GPS CSV is missing required columns: " + ", ".join(sorted(missing))
                )
            if "video_timestamp_seconds" not in headers and "timestamp_utc" not in headers:
                raise ValueError(
                    "GPS CSV needs video_timestamp_seconds or timestamp_utc."
                )

            for line_number, row in enumerate(reader, start=2):
                try:
                    relative_time = (row.get("video_timestamp_seconds") or "").strip()
                    timestamp_utc = (row.get("timestamp_utc") or "").strip() or None
                    if relative_time:
                        frame_time = float(relative_time)
                    elif timestamp_utc:
                        if start_time is None:
                            raise ValueError(
                                "VIDEO_START_TIME_UTC is required when using timestamp_utc."
                            )
                        frame_time = (_parse_utc(timestamp_utc) - start_time).total_seconds()
                    else:
                        raise ValueError("row has no usable timestamp")

                    latitude = float(row["latitude"])
                    longitude = float(row["longitude"])
                    accuracy_text = (row.get("accuracy_m") or "").strip()
                    accuracy = float(accuracy_text) if accuracy_text else None
                    source_name = row["location_source"].strip()
                    simulated = _parse_bool(row["is_simulated"])

                    if not math.isfinite(frame_time):
                        raise ValueError("timestamp must be finite")
                    if not math.isfinite(latitude) or not -90 <= latitude <= 90:
                        raise ValueError("latitude must be between -90 and 90")
                    if not math.isfinite(longitude) or not -180 <= longitude <= 180:
                        raise ValueError("longitude must be between -180 and 180")
                    if accuracy is not None and (
                        not math.isfinite(accuracy) or accuracy < 0
                    ):
                        raise ValueError("accuracy_m must be a non-negative number")
                    if not source_name:
                        raise ValueError("location_source cannot be empty")

                    fixes.append(
                        LocationFix(
                            video_timestamp_seconds=frame_time,
                            latitude=latitude,
                            longitude=longitude,
                            accuracy_m=accuracy,
                            location_source=source_name,
                            is_simulated=simulated,
                            timestamp_utc=timestamp_utc,
                        )
                    )
                except (TypeError, ValueError) as exc:
                    raise ValueError(f"Invalid GPS CSV row {line_number}: {exc}") from exc

        return cls(
            fixes,
            max_delta_seconds=max_delta_seconds,
            max_accuracy_m=max_accuracy_m,
        )

    def match(self, video_timestamp_seconds: float | None) -> LocationMatch | None:
        """Return the nearest fix only when it falls inside the time tolerance."""
        if video_timestamp_seconds is None:
            return None
        try:
            frame_time = float(video_timestamp_seconds)
        except (TypeError, ValueError):
            return None
        if not math.isfinite(frame_time):
            return None

        index = bisect_left(self.timestamps, frame_time)
        candidates = []
        if index < len(self.fixes):
            candidates.append(self.fixes[index])
        if index > 0:
            candidates.append(self.fixes[index - 1])
        if not candidates:
            return None
        fix = min(candidates, key=lambda item: abs(item.video_timestamp_seconds - frame_time))
        delta = abs(fix.video_timestamp_seconds - frame_time)
        if delta > self.max_delta_seconds:
            return None

        if fix.accuracy_m is None:
            status = "accuracy_unknown"
        elif fix.accuracy_m > self.max_accuracy_m:
            status = "low_accuracy"
        else:
            status = "associated"

        return LocationMatch(
            latitude=fix.latitude,
            longitude=fix.longitude,
            accuracy_m=fix.accuracy_m,
            delta_seconds=delta,
            location_source=fix.location_source,
            is_simulated=fix.is_simulated,
            location_status=status,
            sample_timestamp_seconds=fix.video_timestamp_seconds,
        )
