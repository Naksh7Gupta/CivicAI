"""HTTP API for persisted CivicAI detections."""
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response

from app.database.database import get_connection, initialize_database


app = FastAPI(title="CivicAI API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["GET"],
    allow_headers=["*"],
)


def _severity(confidence):
    if confidence >= 0.9:
        return "High"
    if confidence >= 0.8:
        return "Medium"
    return "Low"


@app.on_event("startup")
def startup():
    initialize_database()


@app.get("/api/potholes")
def list_potholes():
    connection = get_connection()
    try:
        rows = connection.execute(
            """
            SELECT id, last_seen, best_confidence, image
            FROM pothole_tracks
            ORDER BY last_seen DESC
            """
        ).fetchall()
        return [
            {
                "id": f"PH-{row['id']:04d}",
                "timestamp": row["last_seen"],
                "latitude": None,
                "longitude": None,
                "confidence": row["best_confidence"],
                "severity": _severity(row["best_confidence"]),
                "address": "GPS coordinates unavailable",
                "status": "Needs review",
                "image_url": f"/api/potholes/{row['id']}/image",
                "has_image": row["image"] is not None,
            }
            for row in rows
        ]
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
