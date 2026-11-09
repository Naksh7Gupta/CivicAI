"""HTTP API for persisted CivicAI detections and evidence-grounded reports."""
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response

from app.database.database import get_connection, initialize_database
from app.services.reporting import (
    LLMConfigurationError, LLMProviderError,
    generate_area_report, generate_incident_report,
)

app = FastAPI(title="CivicAI API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


@app.on_event("startup")
def startup():
    initialize_database()


@app.get("/api/potholes")
def list_potholes():
    connection = get_connection()
    try:
        rows = connection.execute(
            """SELECT p.id, p.last_seen, p.best_confidence, p.image, p.incident_id,
                      i.reference_latitude AS latitude,
                      i.reference_longitude AS longitude,
                      i.gps_accuracy_m, i.location_source, i.is_simulated,
                      i.location_basis
               FROM pothole_tracks p
               LEFT JOIN incidents i ON i.id=p.incident_id
               ORDER BY p.last_seen DESC"""
        ).fetchall()
        return [{
            "id": f"PH-{row['id']:04d}",
            "record_id": row["id"],
            "incident_id": row["incident_id"],
            "timestamp": row["last_seen"],
            "latitude": row["latitude"],
            "longitude": row["longitude"],
            "gps_accuracy_m": row["gps_accuracy_m"],
            "location_source": row["location_source"],
            "is_simulated": bool(row["is_simulated"]) if row["is_simulated"] is not None else False,
            "location_basis": row["location_basis"],
            "confidence": row["best_confidence"],
            "address": (
                "Simulated camera position" if row["is_simulated"]
                else "Camera GPS estimate (not surveyed)" if row["latitude"] is not None
                else "GPS coordinates unavailable"
            ),
            "status": "Needs field review",
            "image_url": f"/api/potholes/{row['id']}/image",
            "has_image": row["image"] is not None,
        } for row in rows]
    finally:
        connection.close()


@app.get("/api/incidents")
def list_incidents():
    connection = get_connection()
    try:
        rows = connection.execute(
            """SELECT id, first_seen, last_seen, observation_count, best_confidence,
                      reference_latitude, reference_longitude, gps_accuracy_m,
                      location_source, is_simulated, location_basis
               FROM incidents ORDER BY last_seen DESC"""
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        connection.close()


@app.get("/api/potholes/{pothole_id}/image")
def pothole_image(pothole_id: int):
    connection = get_connection()
    try:
        row = connection.execute(
            "SELECT image, image_mime FROM pothole_tracks WHERE id=?", (pothole_id,)
        ).fetchone()
    finally:
        connection.close()
    if row is None or row["image"] is None:
        raise HTTPException(status_code=404, detail="Pothole image is not stored.")
    return Response(content=row["image"], media_type=row["image_mime"])


@app.post("/api/incidents/{incident_id}/report")
def incident_report(incident_id: int):
    try:
        return generate_incident_report(incident_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except LLMConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except LLMProviderError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post("/api/reports/area")
def area_report(start: str | None = None, end: str | None = None):
    try:
        return generate_area_report(start=start, end=end)
    except LLMConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except LLMProviderError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
