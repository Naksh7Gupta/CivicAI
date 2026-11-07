"""Timestamp-based GPS association for video frames.

Coordinates describe the recording device/camera position, not a surveyed
pothole coordinate.
"""
from dataclasses import dataclass
from datetime import datetime, timezone
from math import isfinite


class GPSValidationError(ValueError):
    pass


def parse_timestamp(value):
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise GPSValidationError("Timestamp must be ISO-8601 with a timezone.") from exc
    if value.tzinfo is None or value.utcoffset() is None:
        raise GPSValidationError("Timestamp must include a timezone offset.")
    return value.astimezone(timezone.utc)


@dataclass(frozen=True)
class GPSFix:
    recorded_at: datetime
    latitude: float
    longitude: float
    accuracy_m: float
    source: str = "gps"
    is_simulated: bool = False
    id: int | None = None

    def validated(self):
        timestamp = parse_timestamp(self.recorded_at)
        lat, lon, accuracy = float(self.latitude), float(self.longitude), float(self.accuracy_m)
        if not isfinite(lat) or not -90 <= lat <= 90:
            raise GPSValidationError("Latitude must be finite and between -90 and 90.")
        if not isfinite(lon) or not -180 <= lon <= 180:
            raise GPSValidationError("Longitude must be finite and between -180 and 180.")
        if not isfinite(accuracy) or accuracy <= 0:
            raise GPSValidationError("GPS accuracy must be a finite positive number of metres.")
        if not self.source or not self.source.strip():
            raise GPSValidationError("GPS source must be specified.")
        if self.source == "synthetic" and not self.is_simulated:
            raise GPSValidationError("Synthetic GPS fixes must be marked as simulated.")
        return GPSFix(timestamp, lat, lon, accuracy, self.source.strip(), bool(self.is_simulated), self.id)


@dataclass(frozen=True)
class GPSAssociation:
    latitude: float
    longitude: float
    accuracy_m: float
    source: str
    is_simulated: bool
    method: str
    offset_ms: float
    fix_before_id: int | None
    fix_after_id: int | None


def associate_gps_fixes(fixes, frame_timestamp, *, max_gap_seconds=2.0, max_accuracy_m=15.0):
    """Interpolate between close, provenance-matched fixes; otherwise use a close nearest fix."""
    target = parse_timestamp(frame_timestamp)
    if max_gap_seconds <= 0 or max_accuracy_m <= 0:
        raise ValueError("Association limits must be positive.")
    valid = [fix.validated() for fix in fixes]
    valid = sorted((fix for fix in valid if fix.accuracy_m <= max_accuracy_m),
                   key=lambda fix: fix.recorded_at)
    if not valid:
        return None
    before = next((fix for fix in reversed(valid) if fix.recorded_at <= target), None)
    after = next((fix for fix in valid if fix.recorded_at >= target), None)
    if before and after and before.recorded_at == after.recorded_at:
        offset = abs((before.recorded_at - target).total_seconds()) * 1000
        return GPSAssociation(before.latitude, before.longitude, before.accuracy_m,
                              before.source, before.is_simulated, "exact", offset,
                              before.id, after.id)
    if before and after:
        left = (target - before.recorded_at).total_seconds()
        right = (after.recorded_at - target).total_seconds()
        span = (after.recorded_at - before.recorded_at).total_seconds()
        same_provenance = before.source == after.source and before.is_simulated == after.is_simulated
        if same_provenance and left <= max_gap_seconds and right <= max_gap_seconds and 0 < span <= 2 * max_gap_seconds:
            ratio = left / span
            return GPSAssociation(
                before.latitude + (after.latitude - before.latitude) * ratio,
                before.longitude + (after.longitude - before.longitude) * ratio,
                max(before.accuracy_m, after.accuracy_m), before.source,
                before.is_simulated, "linear_interpolation", max(left, right) * 1000,
                before.id, after.id,
            )
    candidates = [fix for fix in (before, after) if fix is not None]
    if not candidates:
        return None
    nearest = min(candidates, key=lambda fix: abs((fix.recorded_at - target).total_seconds()))
    offset = abs((nearest.recorded_at - target).total_seconds())
    if offset > max_gap_seconds:
        return None
    return GPSAssociation(nearest.latitude, nearest.longitude, nearest.accuracy_m,
                          nearest.source, nearest.is_simulated, "nearest", offset * 1000,
                          nearest.id if nearest.recorded_at <= target else None,
                          nearest.id if nearest.recorded_at >= target else None)
