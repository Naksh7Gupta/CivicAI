import pytest

from app.services.gps_association import GPSSample, associate_position, haversine_distance_m


def sample(t, lat, lon, accuracy=5.0, source="real"):
    return GPSSample(
        video_time_ms=t,
        latitude=lat,
        longitude=lon,
        accuracy_m=accuracy,
        source=source,
        is_simulated=(source == "synthetic"),
    )


def test_nearest_sample_within_tolerance():
    result = associate_position(1_100, [sample(1_000, 29.7, 76.9)])
    assert result.status == "associated"
    assert result.method == "nearest"
    assert result.latitude == pytest.approx(29.7)
    assert result.time_delta_ms == pytest.approx(100)
    assert result.location_kind == "vehicle_position_estimate"


def test_interpolates_between_good_samples():
    result = associate_position(
        500,
        [sample(0, 29.0, 76.0), sample(1_000, 30.0, 77.0)],
    )
    assert result.status == "associated"
    assert result.method == "interpolated"
    assert result.latitude == pytest.approx(29.5)
    assert result.longitude == pytest.approx(76.5)


def test_does_not_associate_stale_sample():
    result = associate_position(10_000, [sample(0, 29.7, 76.9)])
    assert result.status == "unavailable"
    assert result.reason == "gps_sample_outside_time_tolerance"


def test_rejects_missing_or_poor_accuracy():
    missing = associate_position(0, [sample(0, 29.7, 76.9, accuracy=None)])
    poor = associate_position(0, [sample(0, 29.7, 76.9, accuracy=90)])
    assert missing.reason == "no_samples_with_acceptable_accuracy"
    assert poor.reason == "no_samples_with_acceptable_accuracy"


def test_does_not_interpolate_across_real_and_synthetic_sources():
    result = associate_position(
        500,
        [sample(0, 29.0, 76.0, source="real"), sample(1_000, 30.0, 77.0, source="synthetic")],
    )
    assert result.status == "unavailable"
    assert result.reason == "mixed_real_and_synthetic_samples"


def test_rejects_invalid_coordinate_and_source_flags():
    with pytest.raises(ValueError):
        sample(0, 91, 76)
    with pytest.raises(ValueError):
        GPSSample(0, 29, 76, 5, source="synthetic", is_simulated=False)


def test_haversine_distance_is_symmetric_and_positive():
    distance = haversine_distance_m(29.7, 76.9, 29.7001, 76.9)
    assert distance > 0
    assert distance == pytest.approx(haversine_distance_m(29.7001, 76.9, 29.7, 76.9))
