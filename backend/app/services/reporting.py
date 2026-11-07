"""Evidence-grounded LLM reports from persisted CivicAI records.

Verified facts and provenance are assembled from SQLite. The LLM supplies only
a narrative and is explicitly prohibited from inventing measurements, severity,
inspection findings, locations, or authority actions.
"""
import json
import os
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from app.database.database import get_connection
from app.geolocation.association import parse_timestamp


class LLMConfigurationError(RuntimeError):
    pass


class LLMProviderError(RuntimeError):
    pass


class OpenAICompatibleClient:
    def __init__(self, base_url, api_key, model, timeout=45):
        self.base_url, self.api_key, self.model = base_url.rstrip("/"), api_key, model
        self.timeout = timeout

    @classmethod
    def from_environment(cls):
        values = {key: os.getenv(key) for key in
                  ("CIVICAI_LLM_BASE_URL", "CIVICAI_LLM_API_KEY", "CIVICAI_LLM_MODEL")}
        missing = [key for key, value in values.items() if not value]
        if missing:
            raise LLMConfigurationError("LLM is not configured. Set: " + ", ".join(missing))
        return cls(values["CIVICAI_LLM_BASE_URL"], values["CIVICAI_LLM_API_KEY"],
                   values["CIVICAI_LLM_MODEL"])

    def generate_narrative(self, report_type, context):
        system = (
            "You are CivicAI's report-writing component. Use only the supplied JSON. "
            "Write a concise, neutral summary. Do not invent coordinates, dimensions, "
            "depth, area, severity, cause, inspection results, repair status, complaints, "
            "notifications, or authority actions. Model confidence is not physical severity "
            "and is not proof of a defect. Explicitly label simulated coordinates. If the "
            "location basis is camera_position_estimate, state that this is the recording "
            "device position, not a surveyed pothole coordinate. Mention missing data. "
            "Do not claim that an official inspection or submission occurred. Return only "
            'JSON: {"narrative":"..."}'
        )
        body = json.dumps({
            "model": self.model,
            "temperature": 0.1,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": json.dumps(
                    {"report_type": report_type, "verified_database_context": context})},
            ],
        }).encode("utf-8")
        request = Request(self.base_url + "/chat/completions", data=body, method="POST",
                          headers={"Authorization": "Bearer " + self.api_key,
                                   "Content-Type": "application/json"})
        try:
            with urlopen(request, timeout=self.timeout) as response:
                result = json.loads(response.read().decode("utf-8"))
            content = result["choices"][0]["message"]["content"]
            narrative = json.loads(content)["narrative"]
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError,
                KeyError, IndexError, TypeError) as exc:
            raise LLMProviderError(f"LLM request/response failed: {exc}") from exc
        if not isinstance(narrative, str) or not narrative.strip():
            raise LLMProviderError("LLM returned an empty narrative.")
        return narrative.strip()


def build_incident_context(incident_id):
    connection = get_connection()
    try:
        incident = connection.execute("SELECT * FROM incidents WHERE id=?", (incident_id,)).fetchone()
        if incident is None:
            raise KeyError(f"Incident {incident_id} was not found")
        rows = connection.execute(
            """SELECT o.id AS observation_id, o.timestamp, o.frame_timestamp,
                      o.confidence, o.x1, o.y1, o.x2, o.y2, o.latitude, o.longitude,
                      o.gps_accuracy_m, o.location_source, o.is_simulated,
                      o.gps_association_method, o.gps_fix_before_id, o.gps_fix_after_id,
                      p.id AS track_record_id,
                      CASE WHEN p.image IS NULL THEN 0 ELSE 1 END AS has_image
               FROM observations o JOIN pothole_tracks p ON p.id=o.pothole_id
               WHERE o.incident_id=? ORDER BY o.timestamp ASC""", (incident_id,)
        ).fetchall()
    finally:
        connection.close()

    missing = []
    location = None
    if incident["reference_latitude"] is None or incident["reference_longitude"] is None:
        missing.append("No GPS fix was associated with this incident.")
    else:
        location = {
            "latitude": incident["reference_latitude"],
            "longitude": incident["reference_longitude"],
            "accuracy_m": incident["gps_accuracy_m"],
            "source": incident["location_source"],
            "is_simulated": bool(incident["is_simulated"]),
            "basis": incident["location_basis"],
        }
        if incident["is_simulated"]:
            missing.append("Coordinates are simulated and are not a real-world location.")
        if incident["location_basis"] == "camera_position_estimate":
            missing.append("Camera GPS is not a surveyed pothole coordinate; camera-to-road offset is unknown.")
    if not rows or not any(row["has_image"] for row in rows):
        missing.append("No stored evidence image is available for this incident.")
    missing += [
        "No physical dimensions or depth measurements are recorded.",
        "No field inspection result or repair/authority action is recorded.",
    ]
    observations = []
    for row in rows:
        gps = None
        if row["latitude"] is not None and row["longitude"] is not None:
            gps = {
                "latitude": row["latitude"], "longitude": row["longitude"],
                "accuracy_m": row["gps_accuracy_m"], "source": row["location_source"],
                "is_simulated": bool(row["is_simulated"]),
                "association_method": row["gps_association_method"],
                "gps_fix_before_id": row["gps_fix_before_id"],
                "gps_fix_after_id": row["gps_fix_after_id"],
            }
        observations.append({
            "observation_id": row["observation_id"],
            "track_record_id": row["track_record_id"],
            "recorded_at": row["timestamp"],
            "frame_timestamp": row["frame_timestamp"],
            "model_confidence": row["confidence"],
            "bounding_box_pixels": [row["x1"], row["y1"], row["x2"], row["y2"]],
            "camera_gps": gps,
            "has_stored_evidence_image": bool(row["has_image"]),
            "track_best_evidence_image_url": f"/api/potholes/{row['track_record_id']}/image" if row["has_image"] else None,
            "evidence_note": "This is the stored best-confidence crop for the tracker record, not a separate image for every observation." if row["has_image"] else None,
        })
    return {
        "incident": {
            "id": incident["id"], "session_id": incident["session_id"],
            "tracker_id": incident["track_id"], "first_seen": incident["first_seen"],
            "last_seen": incident["last_seen"], "observation_count": incident["observation_count"],
            "best_model_confidence": incident["best_confidence"], "location": location,
        },
        "observations": observations,
        "missing_or_unverified_information": missing,
        "interpretation_limits": [
            "This incident groups one tracker ID within one recording session.",
            "It is not a field-verified pothole or physical severity assessment.",
            "Camera position must not be represented as the exact pothole location.",
        ],
    }


def build_area_context(start=None, end=None):
    if start:
        start = parse_timestamp(start).isoformat()
    if end:
        end = parse_timestamp(end).isoformat()
    if start and end and start > end:
        raise ValueError('Area report start must not be after end.')
    clauses, parameters = [], []
    if start:
        clauses.append("first_seen>=?")
        parameters.append(start)
    if end:
        clauses.append("first_seen<=?")
        parameters.append(end)
    where = " WHERE " + " AND ".join(clauses) if clauses else ""
    connection = get_connection()
    try:
        rows = connection.execute("SELECT * FROM incidents" + where + " ORDER BY first_seen", parameters).fetchall()
    finally:
        connection.close()
    incidents = [{
        "incident_id": row["id"], "session_id": row["session_id"],
        "first_seen": row["first_seen"], "last_seen": row["last_seen"],
        "observation_count": row["observation_count"],
        "best_model_confidence": row["best_confidence"],
        "location_available": row["reference_latitude"] is not None,
        "location_source": row["location_source"],
        "is_simulated": bool(row["is_simulated"]),
        "location_basis": row["location_basis"],
    } for row in rows]
    return {
        "period": {"start": start, "end": end},
        "scope": "All persisted incidents in the selected time window; no polygon or administrative boundary filter is applied.",
        "incident_count": len(incidents),
        "observation_count": sum(item["observation_count"] for item in incidents),
        "incidents": incidents,
        "limitations": [
            "Counts are tracker-level records, not independently field-verified potholes.",
            "No geographic boundary or administrative-area filter is applied to this summary.",
            "Camera GPS is an estimate of recording-device position, not surveyed defect coordinates.",
            "Simulated coordinates are not real locations.",
            "Model confidence is not a physical severity or repair status.",
        ],
    }


def _store_report(report_type, incident_id, context, narrative, model):
    generated_at = datetime.now(timezone.utc).isoformat()
    connection = get_connection()
    try:
        cursor = connection.execute(
            """INSERT INTO generated_reports
               (incident_id, report_type, generated_at, model, context_json, narrative)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (incident_id, report_type, generated_at, model, json.dumps(context), narrative),
        )
        connection.commit()
        report_id = cursor.lastrowid
    finally:
        connection.close()
    return {"report_id": report_id, "report_type": report_type,
            "incident_id": incident_id, "generated_at": generated_at,
            "model": model, "verified_context": context, "narrative": narrative}


def generate_incident_report(incident_id, client=None):
    context = build_incident_context(incident_id)
    client = client or OpenAICompatibleClient.from_environment()
    return _store_report("incident", incident_id, context,
                         client.generate_narrative("incident", context), client.model)


def generate_area_report(start=None, end=None, client=None):
    context = build_area_context(start, end)
    client = client or OpenAICompatibleClient.from_environment()
    return _store_report("area", None, context,
                         client.generate_narrative("area", context), client.model)
