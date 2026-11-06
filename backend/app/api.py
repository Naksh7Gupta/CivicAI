"""HTTP API for persisted CivicAI detections and evidence-grounded reports."""
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response

from app.database.database import get_connection, initialize_database
from app.services.reporting import (
    LLMNotConfigured,
    ReportGenerationError,
    ReportingService,
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
            """
            SELECT
                t.id, t.last_seen, t.best_confidence, t.image,
                (
                    SELECT ol.latitude
                    FROM observations o
                    JOIN observation_locations ol ON ol.observation_id = o.id
                    WHERE o.pothole_id = t.id
                    ORDER BY ol.frame_elapsed_ms DESC LIMIT 1
                ) AS latitude,
                (
                    SELECT ol.longitude
                    FROM observations o
                    JOIN observation_locations ol ON ol.observation_id = o.id
                    WHERE o.pothole_id = t.id
                    ORDER BY ol.frame_elapsed_ms DESC LIMIT 1
                ) AS longitude,
                (
                    SELECT ol.accuracy_m
                    FROM observations o
                    JOIN observation_locations ol ON ol.observation_id = o.id
                    WHERE o.pothole_id = t.id
                    ORDER BY ol.frame_elapsed_ms DESC LIMIT 1
                ) AS accuracy_m,
                (
                    SELECT ol.location_source
                    FROM observations o
                    JOIN observation_locations ol ON ol.observation_id = o.id
                    WHERE o.pothole_id = t.id
                    ORDER BY ol.frame_elapsed_ms DESC LIMIT 1
                ) AS location_source,
                (
                    SELECT ol.is_simulated
                    FROM observations o
                    JOIN observation_locations ol ON ol.observation_id = o.id
                    WHERE o.pothole_id = t.id
                    ORDER BY ol.frame_elapsed_ms DESC LIMIT 1
                ) AS is_simulated
            FROM pothole_tracks t
            ORDER BY t.last_seen DESC
            """
        ).fetchall()
        output = []
        for row in rows:
            if row["latitude"] is None:
                address = "GPS coordinates unavailable"
            elif row["is_simulated"]:
                address = "Simulated GPS position"
            else:
                address = "Estimated vehicle GPS position"
            output.append(
                {
                    "id": f"PH-{row['id']:04d}",
                    "timestamp": row["last_seen"],
                    "latitude": row["latitude"],
                    "longitude": row["longitude"],
                    "gps_accuracy_m": row["accuracy_m"],
                    "location_source": row["location_source"],
                    "is_simulated": bool(row["is_simulated"]) if row["is_simulated"] is not None else None,
                    "confidence": row["best_confidence"],
                    "severity": "Unassessed",
                    "address": address,
                    "status": "Needs review",
                    "image_url": f"/api/potholes/{row['id']}/image",
                    "has_image": row["image"] is not None,
                }
            )
        return output
    finally:
        connection.close()


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


@app.get("/api/incidents")
def list_incidents():
    connection = get_connection()
    try:
        rows = connection.execute(
            """
            SELECT id, category, first_seen, last_seen, best_confidence,
                   latitude, longitude, location_accuracy_m, location_source,
                   is_simulated, location_semantics, status, merge_method
            FROM incidents
            ORDER BY last_seen DESC
            """
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        connection.close()


@app.get("/api/incidents/{incident_id}")
def incident_evidence(incident_id: int):
    try:
        return ReportingService().build_incident_evidence(incident_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/incidents/{incident_id}/report")
def create_incident_report(incident_id: int):
    try:
        return ReportingService().generate_incident_report(incident_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except LLMNotConfigured as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ReportGenerationError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get("/api/reports/{report_id}")
def get_report(report_id: int):
    try:
        return ReportingService().get_report(report_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
