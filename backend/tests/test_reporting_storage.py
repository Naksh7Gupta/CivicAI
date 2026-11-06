from app.database import database
from app.database.database import initialize_database
from app.database.repository import add_observation, create_track
from app.reporting.engine import generate_incident_report
from app.services.gps_repository import associate_session_observations, save_gps_samples
from app.services.incident_repository import list_incidents


def setup_database(monkeypatch, tmp_path):
    monkeypatch.setattr(database, "DATABASE_PATH", tmp_path / "civicai-test.db")
    initialize_database()


def test_gps_samples_backfill_observations_and_create_track_incident(monkeypatch, tmp_path):
    setup_database(monkeypatch, tmp_path)
    track_id = create_track(
        "session-1", 7, "2026-11-06T10:00:00+00:00", 0.83,
        (10, 20, 40, 60), None,
    )
    add_observation(
        track_id, "2026-11-06T10:00:01+00:00", 0.83,
        (10, 20, 40, 60), video_time_ms=1_000,
    )
    saved = save_gps_samples("session-1", [{
        "video_time_ms": 1_000,
        "latitude": 29.6857,
        "longitude": 76.9905,
        "accuracy_m": 6.0,
        "source": "real",
        "is_simulated": False,
        "captured_at_utc": None,
    }])
    reprocessed = associate_session_observations("session-1")

    assert saved == 1
    assert reprocessed == 1
    incident = list_incidents("session-1")[0]
    assert incident["observation_count"] == 1
    assert incident["latitude"] == 29.6857
    assert incident["longitude"] == 76.9905
    assert incident["location_kind"] == "vehicle_position_estimate"
    assert incident["severity"] == "not_assessed"


def test_synthetic_gps_is_explicit_in_incident_and_report(monkeypatch, tmp_path):
    setup_database(monkeypatch, tmp_path)
    track_id = create_track(
        "session-demo", 3, "2026-11-06T10:00:00+00:00", 0.91,
        (1, 2, 30, 40), None,
    )
    add_observation(
        track_id, "2026-11-06T10:00:01+00:00", 0.91,
        (1, 2, 30, 40), video_time_ms=500,
    )
    save_gps_samples("session-demo", [{
        "video_time_ms": 500,
        "latitude": 29.0,
        "longitude": 76.0,
        "accuracy_m": 4.0,
        "source": "synthetic",
        "is_simulated": True,
        "captured_at_utc": None,
    }])
    associate_session_observations("session-demo")

    monkeypatch.delenv("CIVICAI_LLM_API_KEY", raising=False)
    monkeypatch.delenv("CIVICAI_LLM_MODEL", raising=False)
    report = generate_incident_report(track_id)

    assert report["facts"]["is_simulated"] is True
    assert any("simulated" in notice.lower() for notice in report["notices"])
    assert report["severity"]["status"] == "not_assessed"
    assert report["narrative"]["status"] == "not_configured"


def test_unassociated_observation_stays_without_coordinates(monkeypatch, tmp_path):
    setup_database(monkeypatch, tmp_path)
    track_id = create_track(
        "session-no-gps", 1, "2026-11-06T10:00:00+00:00", 0.77,
        (1, 2, 3, 4), None,
    )
    add_observation(
        track_id, "2026-11-06T10:00:01+00:00", 0.77,
        (1, 2, 3, 4), video_time_ms=100,
    )
    associate_session_observations("session-no-gps")
    incident = list_incidents("session-no-gps")[0]
    assert incident["latitude"] is None
    assert incident["longitude"] is None
    assert incident["is_simulated"] is False
