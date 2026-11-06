"""HTTP API for CivicAI detections, GPS association, incidents, and reports."""
from typing import Literal

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from pydantic import BaseModel, Field

from app.database.database import get_connection, initialize_database
from app.reporting.engine import generate_incident_report, generate_session_summary
from app.services.gps_repository import associate_session_observations, save_gps_samples
from app.services.incident_repository import list_incidents


app = FastAPI(title="CivicAI API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


class GPSSampleInput(BaseModel):
    video_time_ms: float = Field(ge=0)
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    accuracy_m: float | None = Field(default=None, ge=0)
    source: Literal["real", "synthetic"] = "real"
    captured_at_utc: str | None = None


class GPSSamplesPayload(BaseModel):
    samples: list[GPSSampleInput] = Field(min_length=1, max_length=100_000)


@app.on_event("startup")
def startup():
    initialize_database()


@app.get("/api/potholes")
def list_potholes():
    """Backward-compatible dashboard response; confidence is not severity."""
    return [
        {
            "id": item["id"],
            "track_record_id": item["track_record_id"],
            "timestamp": item["last_seen"],
            "timestamp_kind": "processing_time_utc",
            "latitude": item["latitude"],
            "longitude": item["longitude"],
            "gps_accuracy_m": item["gps_accuracy_m"],
            "location_source": item["location_source"],
            "location_kind": item["location_kind"],
            "is_simulated": item["is_simulated"],
            "confidence": item["best_detection_confidence"],
            "severity": "Unassessed",
            "severity_status": "not_assessed",
            "address": (
                "Approximate vehicle GPS position"
                if item["latitude"] is not None
                else "GPS coordinates unavailable"
            ),
            "status": "Needs review",
            "image_url": item["image_url"],
            "has_image": item["has_image"],
            "observation_count": item["observation_count"],
        }
        for item in list_incidents()
    ]


@app.get("/api/incidents")
def incidents(session_id: str | None = None):
    return list_incidents(session_id=session_id)


@app.post("/api/sessions/{session_id}/gps-samples")
def upload_gps_samples(session_id: str, payload: GPSSamplesPayload):
    """Upload a GPS sidecar and associate it with persisted frame observations."""
    samples = [
        {
            **sample.model_dump(),
            "is_simulated": sample.source == "synthetic",
        }
        for sample in payload.samples
    ]
    try:
        saved = save_gps_samples(session_id, samples)
        reprocessed = associate_session_observations(session_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {
        "session_id": session_id,
        "gps_samples_saved": saved,
        "timestamped_observations_reprocessed": reprocessed,
        "location_kind": "vehicle_position_estimate",
        "note": (
            "GPS positions are associated by video-relative timestamps. They represent "
            "the recording phone/vehicle position, not an exact pothole coordinate."
        ),
        "synthetic_samples_are_labelled": True,
    }


@app.get("/api/reports/incidents/{track_record_id}")
def incident_report(track_record_id: int):
    report = generate_incident_report(track_record_id)
    if report is None:
        raise HTTPException(status_code=404, detail="Incident record not found.")
    return report


@app.get("/api/reports/summary")
def report_summary(session_id: str | None = None):
    return generate_session_summary(session_id=session_id)


@app.get("/api/potholes/{pothole_id}/image")
def pothole_image(pothole_id: int):
    connection = get_connection()
    try:
        row = connection.execute(
            "SELECT image, image_mime FROM pothole_tracks WHERE id = ?",
            (pothole_id,),
        ).fetchone()
    finally:
        connection.close()

    if row is None or row["image"] is None:
        raise HTTPException(status_code=404, detail="Pothole image is not stored.")
    return Response(content=row["image"], media_type=row["image_mime"])
