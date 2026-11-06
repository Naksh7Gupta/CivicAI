"""Timestamp-based GPS association for CivicAI video frames."""
import csv
import math
from bisect import bisect_left
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class GPSSample:
    sample_index: int
    elapsed_ms: float
    latitude: float
    longitude: float
    accuracy_m: float | None
    source: str
    is_simulated: bool


@dataclass(frozen=True)
class GPSMatch:
    latitude: float
    longitude: float
    accuracy_m: float | None
    source: str
    is_simulated: bool
    method: str
    before_sample_index: int
    after_sample_index: int
    time_delta_ms: float


def _parse_bool(value: str) -> bool:
    normalized = str(value).strip().lower()
    if normalized in {"1", "true", "yes", "y"}:
        return True
    if normalized in {"0", "false", "no", "n"}:
        return False
    raise ValueError(f"Invalid is_simulated value: {value!r}")


def load_gps_csv(path: str | Path) -> list[GPSSample]:
    """Load a sidecar trace. Times must be milliseconds from video start."""
    samples: list[GPSSample] = []
    with Path(path).open("r", newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        required = {"elapsed_ms", "latitude", "longitude"}
        if not reader.fieldnames or not required.issubset(reader.fieldnames):
            raise ValueError(
                "GPS CSV must contain elapsed_ms, latitude and longitude columns."
            )

        for row_number, row in enumerate(reader):
            try:
                elapsed_ms = float(row["elapsed_ms"])
                latitude = float(row["latitude"])
                longitude = float(row["longitude"])
                accuracy_raw = (row.get("accuracy_m") or "").strip()
                accuracy_m = float(accuracy_raw) if accuracy_raw else None
                source = (row.get("source") or "unknown").strip().lower()
                simulated_raw = row.get("is_simulated")
                is_simulated = _parse_bool(simulated_raw) if simulated_raw not in (None, "") else source == "synthetic"
                sample_index_raw = (row.get("sample_index") or "").strip()
                sample_index = int(sample_index_raw) if sample_index_raw else row_number
            except (TypeError, ValueError) as exc:
                raise ValueError(f"Invalid GPS CSV row {row_number + 2}: {exc}") from exc

            numeric_values = [elapsed_ms, latitude, longitude]
            if accuracy_m is not None:
                numeric_values.append(accuracy_m)
            if not all(math.isfinite(value) for value in numeric_values):
                raise ValueError(f"GPS CSV row {row_number + 2} contains a non-finite value.")
            if elapsed_ms < 0:
                raise ValueError(f"GPS CSV row {row_number + 2} has negative elapsed_ms.")
            if not -90 <= latitude <= 90 or not -180 <= longitude <= 180:
                raise ValueError(f"GPS CSV row {row_number + 2} has invalid coordinates.")
            if accuracy_m is not None and accuracy_m < 0:
                raise ValueError(f"GPS CSV row {row_number + 2} has negative accuracy_m.")
            if not source:
                raise ValueError(f"GPS CSV row {row_number + 2} has an empty source.")
            if source == "synthetic" and not is_simulated:
                raise ValueError("A source='synthetic' sample must set is_simulated=true.")

            samples.append(
                GPSSample(
                    sample_index=sample_index,
                    elapsed_ms=elapsed_ms,
                    latitude=latitude,
                    longitude=longitude,
                    accuracy_m=accuracy_m,
                    source=source,
                    is_simulated=is_simulated,
                )
            )

    samples.sort(key=lambda sample: sample.elapsed_ms)
    elapsed_values = [sample.elapsed_ms for sample in samples]
    if len(elapsed_values) != len(set(elapsed_values)):
        raise ValueError("GPS CSV contains duplicate elapsed_ms timestamps.")
    indexes = [sample.sample_index for sample in samples]
    if len(indexes) != len(set(indexes)):
        raise ValueError("GPS CSV contains duplicate sample_index values.")
    return samples


class GPSAssociator:
    """Matches frame times to GPS samples without inventing missing positions."""

    def __init__(
        self,
        samples: list[GPSSample],
        max_nearest_age_ms: float = 1500.0,
        max_interpolation_gap_ms: float = 3000.0,
    ):
        self.samples = sorted(samples, key=lambda sample: sample.elapsed_ms)
        self.times = [sample.elapsed_ms for sample in self.samples]
        self.max_nearest_age_ms = float(max_nearest_age_ms)
        self.max_interpolation_gap_ms = float(max_interpolation_gap_ms)

    def associate(self, frame_elapsed_ms: float | None) -> GPSMatch | None:
        if frame_elapsed_ms is None:
            return None
        try:
            frame_time = float(frame_elapsed_ms)
        except (TypeError, ValueError):
            return None
        if not math.isfinite(frame_time) or frame_time < 0 or not self.samples:
            return None

        right_index = bisect_left(self.times, frame_time)

        if 0 < right_index < len(self.samples):
            before = self.samples[right_index - 1]
            after = self.samples[right_index]
            gap = after.elapsed_ms - before.elapsed_ms
            compatible = (
                before.source == after.source
                and before.is_simulated == after.is_simulated
            )
            if (
                0 < gap <= self.max_interpolation_gap_ms
                and compatible
                and before.elapsed_ms <= frame_time <= after.elapsed_ms
            ):
                fraction = (frame_time - before.elapsed_ms) / gap
                accuracy = (
                    max(before.accuracy_m, after.accuracy_m)
                    if before.accuracy_m is not None and after.accuracy_m is not None
                    else None
                )
                return GPSMatch(
                    latitude=before.latitude + fraction * (after.latitude - before.latitude),
                    longitude=before.longitude + fraction * (after.longitude - before.longitude),
                    accuracy_m=accuracy,
                    source=before.source,
                    is_simulated=before.is_simulated,
                    method="linear_interpolation",
                    before_sample_index=before.sample_index,
                    after_sample_index=after.sample_index,
                    time_delta_ms=max(frame_time - before.elapsed_ms, after.elapsed_ms - frame_time),
                )

        candidates = []
        if right_index < len(self.samples):
            candidates.append(self.samples[right_index])
        if right_index > 0:
            candidates.append(self.samples[right_index - 1])
        nearest = min(candidates, key=lambda sample: abs(sample.elapsed_ms - frame_time))
        delta = abs(nearest.elapsed_ms - frame_time)
        if delta > self.max_nearest_age_ms:
            return None

        return GPSMatch(
            latitude=nearest.latitude,
            longitude=nearest.longitude,
            accuracy_m=nearest.accuracy_m,
            source=nearest.source,
            is_simulated=nearest.is_simulated,
            method="nearest_sample",
            before_sample_index=nearest.sample_index,
            after_sample_index=nearest.sample_index,
            time_delta_ms=delta,
        )
