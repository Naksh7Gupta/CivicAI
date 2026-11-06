"""Timestamp-based GPS association for video observations.

Coordinates describe the recording vehicle/phone position at a frame time.
They are not a surveyed pothole coordinate unless a separate camera-to-road
projection has been calibrated.
"""
from dataclasses import asdict, dataclass
from math import asin, cos, isfinite, radians, sin, sqrt
from typing import Iterable, Mapping, Optional


@dataclass(frozen=True)
class GPSSample:
    video_time_ms: float
    latitude: float
    longitude: float
    accuracy_m: Optional[float]
    source: str = "real"
    is_simulated: bool = False

    def __post_init__(self) -> None:
        values = (self.video_time_ms, self.latitude, self.longitude)
        if not all(isfinite(float(value)) for value in values):
            raise ValueError("GPS time and coordinates must be finite numbers.")
        if self.video_time_ms < 0:
            raise ValueError("video_time_ms cannot be negative.")
        if not -90 <= self.latitude <= 90:
            raise ValueError("latitude must be between -90 and 90.")
        if not -180 <= self.longitude <= 180:
            raise ValueError("longitude must be between -180 and 180.")
        if self.accuracy_m is not None:
            if not isfinite(float(self.accuracy_m)) or self.accuracy_m < 0:
                raise ValueError("accuracy_m must be a finite non-negative number.")
        if self.source not in {"real", "synthetic"}:
            raise ValueError("source must be either 'real' or 'synthetic'.")
        if self.is_simulated != (self.source == "synthetic"):
            raise ValueError("source and is_simulated must agree.")

    @classmethod
    def from_mapping(cls, value: Mapping) -> "GPSSample":
        source = str(value.get("source", "real"))
        return cls(
            video_time_ms=float(value["video_time_ms"]),
            latitude=float(value["latitude"]),
            longitude=float(value["longitude"]),
            accuracy_m=None if value.get("accuracy_m") is None else float(value["accuracy_m"]),
            source=source,
            is_simulated=bool(value.get("is_simulated", source == "synthetic")),
        )


@dataclass(frozen=True)
class GPSAssociation:
    status: str
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    accuracy_m: Optional[float] = None
    source: Optional[str] = None
    is_simulated: bool = False
    method: str = "unavailable"
    time_delta_ms: Optional[float] = None
    reason: Optional[str] = None
    location_kind: str = "vehicle_position_estimate"

    def to_dict(self) -> dict:
        return asdict(self)


def _unavailable(reason: str) -> GPSAssociation:
    return GPSAssociation(status="unavailable", reason=reason)


def associate_position(
    video_time_ms: float,
    samples: Iterable[GPSSample | Mapping],
    *,
    max_nearest_delta_ms: float = 2_000,
    max_interpolation_gap_ms: float = 10_000,
    max_accuracy_m: float = 50.0,
) -> GPSAssociation:
    """Match a frame PTS to a good GPS sample or interpolate between samples."""
    if not isfinite(float(video_time_ms)) or video_time_ms < 0:
        return _unavailable("invalid_video_time")

    normalized = [
        sample if isinstance(sample, GPSSample) else GPSSample.from_mapping(sample)
        for sample in samples
    ]
    if not normalized:
        return _unavailable("no_gps_samples")

    usable = [
        sample for sample in normalized
        if sample.accuracy_m is not None and sample.accuracy_m <= max_accuracy_m
    ]
    if not usable:
        return _unavailable("no_samples_with_acceptable_accuracy")

    usable.sort(key=lambda sample: sample.video_time_ms)
    before = next(
        (sample for sample in reversed(usable) if sample.video_time_ms <= video_time_ms),
        None,
    )
    after = next(
        (sample for sample in usable if sample.video_time_ms >= video_time_ms),
        None,
    )

    if before is not None and after is not None and before is not after:
        if before.source != after.source or before.is_simulated != after.is_simulated:
            return _unavailable("mixed_real_and_synthetic_samples")
        gap = after.video_time_ms - before.video_time_ms
        if 0 < gap <= max_interpolation_gap_ms:
            ratio = (video_time_ms - before.video_time_ms) / gap
            latitude = before.latitude + (after.latitude - before.latitude) * ratio
            longitude_delta = ((after.longitude - before.longitude + 180) % 360) - 180
            longitude = ((before.longitude + longitude_delta * ratio + 180) % 360) - 180
            return GPSAssociation(
                status="associated",
                latitude=latitude,
                longitude=longitude,
                accuracy_m=max(before.accuracy_m, after.accuracy_m),
                source=before.source,
                is_simulated=before.is_simulated,
                method="interpolated",
                time_delta_ms=0.0,
            )

    nearest = min(usable, key=lambda sample: abs(sample.video_time_ms - video_time_ms))
    delta = abs(nearest.video_time_ms - video_time_ms)
    if delta > max_nearest_delta_ms:
        return _unavailable("gps_sample_outside_time_tolerance")

    return GPSAssociation(
        status="associated",
        latitude=nearest.latitude,
        longitude=nearest.longitude,
        accuracy_m=nearest.accuracy_m,
        source=nearest.source,
        is_simulated=nearest.is_simulated,
        method="nearest",
        time_delta_ms=delta,
    )


def haversine_distance_m(latitude_a, longitude_a, latitude_b, longitude_b) -> float:
    """Return great-circle distance in metres between two coordinate pairs."""
    lat_a, lat_b = radians(latitude_a), radians(latitude_b)
    delta_lat = lat_b - lat_a
    delta_lon = radians(longitude_b - longitude_a)
    value = sin(delta_lat / 2) ** 2 + cos(lat_a) * cos(lat_b) * sin(delta_lon / 2) ** 2
    return 6_371_000 * 2 * asin(sqrt(min(1.0, value)))
