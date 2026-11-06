"""HTTP API for persisted CivicAI incidents and evidence-grounded reports."""
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response

from app.database.database import get_connection, initialize_database
from app.database.repository import get_incident_report_context, list_incidents
from app.services.reporting import ReportGenerator

app = FastAPI(title="CivicAI API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["GET"],
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
            SELECT t.id, t.last_seen, t.best_confidence, t.image,
                   t.incident_id, i.latitude, i.longitude, i.location_source,
                   i.is_simulated, i.gps_accuracy_m, i.location_status
            FROM pothole_tracks t
            LEFT JOIN incidents i ON i.id = t.incident_id
            ORDER BY t.last_seen DESC
            """
        ).fetchall()
        result = []
        for row in rows:
            has_coordinates = row["latitude"] is not None and row["longitude"] is not None
            if not has_coordinates:
                address = "GPS coordinates unavailable"
            elif row["is_simulated"]:
                address = "Simulated coordinates (not a real location)"
            elif row["location_status"] == "low_accuracy":
                address = "Low-accuracy GPS camera/vehicle position; not a surveyed pothole location"
            elif row["location_status"] == "accuracy_unknown":
                address = "GPS camera/vehicle position; accuracy unknown; not a surveyed pothole location"
            else:
                address = "GPS-associated camera/vehicle position; not surveyed pothole location"
            result.append(
                {
                    "id": f"PH-{row['id']:04d}",
                    "incident_id": row["incident_id"],
                    "timestamp": row["last_seen"],
                    "latitude": row["latitude"],
                    "longitude": row["longitude"],
                    "confidence": row["best_confidence"],
                    "severity": "Not assessed",
                    "address": address,
                    "location_source": row["location_source"],
                    "is_simulated": None if row["is_simulated"] is None else bool(row["is_simulated"]),
                    "gps_accuracy_m": row["gps_accuracy_m"],
                    "location_status": row["location_status"] or "unavailable",
                    "status": "Needs review",
                    "image_url": f"/api/potholes/{row['id']}/image",
                    "has_image": row["image"] is not None,
                }
            )
        return result
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
def incidents(session_id: str | None = Query(default=None)):
    return list_incidents(session_id)


@app.get("/api/incidents/{incident_id}/report")
def incident_report(incident_id: int):
    try:
        return ReportGenerator().generate_incident_report(incident_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/api/reports/area")
def area_report(session_id: str | None = Query(default=None)):
    return ReportGenerator().generate_area_report(session_id)


@app.get("/api/reports/executive-summary")
def executive_summary(session_id: str | None = Query(default=None)):
    return ReportGenerator().generate_executive_summary(session_id)
