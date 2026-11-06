"""Evidence-grounded incident report generation."""
import json
import os
import urllib.error
import urllib.request
from datetime import datetime, timezone
from urllib.parse import quote

from app.database.database import get_connection


PROMPT_VERSION = "incident-report-v1"


class LLMNotConfigured(RuntimeError):
    pass


class ReportGenerationError(RuntimeError):
    pass


class ReportValidationError(ReportGenerationError):
    pass


def validate_llm_payload(payload, evidence_ids):
    if not isinstance(payload, dict):
        raise ReportValidationError("The model response must be a JSON object.")
    narrative = payload.get("narrative")
    narrative_refs = payload.get("narrative_evidence_ids")
    follow_up = payload.get("follow_up", [])
    allowed = set(evidence_ids)

    if not isinstance(narrative, str) or not narrative.strip():
        raise ReportValidationError("The model did not return a narrative.")
    if not isinstance(narrative_refs, list) or not narrative_refs:
        raise ReportValidationError("The narrative must cite at least one evidence ID.")
    if any(reference not in allowed for reference in narrative_refs):
        raise ReportValidationError("The narrative contains an unknown evidence ID.")
    if not isinstance(follow_up, list):
        raise ReportValidationError("follow_up must be a list.")

    validated_follow_up = []
    for item in follow_up:
        if not isinstance(item, dict) or not isinstance(item.get("text"), str):
            raise ReportValidationError("Each follow-up item must contain text.")
        references = item.get("evidence_ids")
        if not isinstance(references, list) or not references:
            raise ReportValidationError("Each follow-up item must cite evidence.")
        if any(reference not in allowed for reference in references):
            raise ReportValidationError("A follow-up item contains an unknown evidence ID.")
        validated_follow_up.append(
            {"text": item["text"].strip(), "evidence_ids": references}
        )

    return {
        "narrative": narrative.strip(),
        "narrative_evidence_ids": narrative_refs,
        "follow_up": validated_follow_up,
    }


class ReportingService:
    def build_incident_evidence(self, incident_id):
        connection = get_connection()
        try:
            incident_row = connection.execute(
                "SELECT * FROM incidents WHERE id = ?", (incident_id,)
            ).fetchone()
            if incident_row is None:
                raise KeyError(f"Incident {incident_id} was not found.")
            incident = dict(incident_row)

            tracks = connection.execute(
                """
                SELECT t.id, t.session_id, t.track_id, t.first_seen, t.last_seen,
                       t.best_confidence, t.image IS NOT NULL AS has_image
                FROM incident_tracks it
                JOIN pothole_tracks t ON t.id = it.pothole_track_id
                WHERE it.incident_id = ?
                ORDER BY t.first_seen
                """,
                (incident_id,),
            ).fetchall()

            observations = connection.execute(
                """
                SELECT o.id, o.pothole_id, o.timestamp, o.confidence,
                       o.x1, o.y1, o.x2, o.y2,
                       t.image IS NOT NULL AS has_image,
                       ol.latitude, ol.longitude, ol.accuracy_m,
                       ol.location_source, ol.is_simulated, ol.method,
                       ol.location_semantics
                FROM incident_tracks it
                JOIN observations o ON o.pothole_id = it.pothole_track_id
                JOIN pothole_tracks t ON t.id = o.pothole_id
                LEFT JOIN observation_locations ol ON ol.observation_id = o.id
                WHERE it.incident_id = ?
                ORDER BY o.timestamp, o.id
                """,
                (incident_id,),
            ).fetchall()
        finally:
            connection.close()

        evidence = []
        for row in observations:
            item = dict(row)
            location = None
            if item["latitude"] is not None and item["longitude"] is not None:
                location = {
                    "latitude": item["latitude"],
                    "longitude": item["longitude"],
                    "accuracy_m": item["accuracy_m"],
                    "source": item["location_source"],
                    "is_simulated": bool(item["is_simulated"]),
                    "method": item["method"],
                    "semantics": item["location_semantics"],
                }
            evidence.append(
                {
                    "evidence_id": f"OBS-{item['id']}",
                    "timestamp": item["timestamp"],
                    "model_confidence": item["confidence"],
                    "bounding_box_xyxy": [
                        item["x1"], item["y1"], item["x2"], item["y2"]
                    ],
                    "location": location,
                    "image_url": (
                        f"/api/potholes/{item['pothole_id']}/image"
                        if item["has_image"] else None
                    ),
                }
            )

        location = None
        if incident["latitude"] is not None and incident["longitude"] is not None:
            location = {
                "latitude": incident["latitude"],
                "longitude": incident["longitude"],
                "accuracy_m": incident["location_accuracy_m"],
                "source": incident["location_source"],
                "is_simulated": bool(incident["is_simulated"]),
                "semantics": incident["location_semantics"],
            }

        limitations = [
            "Observation timestamps currently record backend processing time, not the original camera capture time.",
            "No physical pothole dimensions or depth measurement are recorded.",
            "No human field-inspection result is recorded.",
            "No official repair, work-order, or completion status is recorded.",
            "Model confidence is not a measurement of physical severity.",
            "GPS-radius grouping is a provisional heuristic; nearby separate potholes may be merged or repeated passes may remain split.",
        ]
        if location is None:
            limitations.append("No GPS coordinates were associated with this incident.")
        elif location["is_simulated"]:
            limitations.append(
                "The associated coordinates are synthetic test data, not a real-world location."
            )
        else:
            limitations.append(
                "The coordinates estimate the recording vehicle position; they are not a surveyed pothole position."
            )

        verified_facts = {
            "incident_id": incident["id"],
            "category": incident["category"],
            "first_seen": incident["first_seen"],
            "last_seen": incident["last_seen"],
            "track_count": len(tracks),
            "observation_count": len(evidence),
            "best_model_confidence": incident["best_confidence"],
            "workflow_status": incident["status"],
            "grouping_method": incident["merge_method"],
            "location": location,
        }
        return {
            "verified_facts": verified_facts,
            "limitations": limitations,
            "tracks": [
                {
                    "track_record_id": row["id"],
                    "session_id": row["session_id"],
                    "tracker_id": row["track_id"],
                    "first_seen": row["first_seen"],
                    "last_seen": row["last_seen"],
                    "best_model_confidence": row["best_confidence"],
                    "has_image": bool(row["has_image"]),
                }
                for row in tracks
            ],
            "evidence": evidence,
        }

    def _call_gemini(self, evidence_packet):
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise LLMNotConfigured(
                "Set GEMINI_API_KEY in backend/.env to enable LLM report generation."
            )
        model = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
        prompt = (
            "You write a cautious civic infrastructure observation report. "
            "Use only the JSON evidence supplied below. Do not invent or infer "
            "physical severity, pothole dimensions, depth, cause, exact address, "
            "municipal jurisdiction, human inspection, repair, or authority action. "
            "Never treat model confidence as severity. Do not say the pothole is "
            "confirmed; call it a model-detected candidate. If coordinates are "
            "synthetic, explicitly say they are simulated. If the location is a "
            "vehicle-position estimate, do not describe it as the exact pothole "
            "position. Return JSON only with keys: narrative, narrative_evidence_ids, "
            "follow_up. narrative_evidence_ids must contain valid evidence_id values. "
            "Each follow_up item must have text and a non-empty evidence_ids array. "
            "If there is insufficient evidence, say so rather than guessing.\n\n"
            "EVIDENCE JSON:\n"
            + json.dumps(evidence_packet, ensure_ascii=False)
        )
        url = (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            + quote(model, safe="")
            + ":generateContent"
        )
        body = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": 0.2,
                "responseMimeType": "application/json",
            },
        }
        request = urllib.request.Request(
            url,
            data=json.dumps(body).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "x-goog-api-key": api_key,
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=45) as response:
                result = json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise ReportGenerationError(
                "The LLM provider request failed. Check connectivity, model name and API quota."
            ) from exc

        try:
            text = "".join(
                part.get("text", "")
                for part in result["candidates"][0]["content"]["parts"]
            )
            return json.loads(text), model
        except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
            raise ReportGenerationError(
                "The LLM provider returned an invalid JSON report."
            ) from exc

    def generate_incident_report(self, incident_id):
        evidence_packet = self.build_incident_evidence(incident_id)
        valid_ids = [item["evidence_id"] for item in evidence_packet["evidence"]]
        if not valid_ids:
            raise ReportGenerationError(
                "This incident has no persisted observation evidence to cite."
            )
        model_payload, model = self._call_gemini(evidence_packet)
        validated = validate_llm_payload(model_payload, valid_ids)
        report = {
            "report_type": "incident",
            "incident_id": incident_id,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "generation_mode": "llm",
            "model": model,
            "verified_facts": evidence_packet["verified_facts"],
            "narrative": validated["narrative"],
            "narrative_evidence_ids": validated["narrative_evidence_ids"],
            "follow_up": validated["follow_up"],
            "limitations": evidence_packet["limitations"],
            "evidence": evidence_packet["evidence"],
        }

        connection = get_connection()
        try:
            cursor = connection.execute(
                """
                INSERT INTO generated_reports (
                    report_type, target_id, model, prompt_version,
                    evidence_json, report_json, created_at
                ) VALUES ('incident', ?, ?, ?, ?, '{}', ?)
                """,
                (
                    incident_id,
                    model,
                    PROMPT_VERSION,
                    json.dumps(evidence_packet, ensure_ascii=False),
                    report["generated_at"],
                ),
            )
            report["report_id"] = cursor.lastrowid
            connection.execute(
                "UPDATE generated_reports SET report_json = ? WHERE id = ?",
                (json.dumps(report, ensure_ascii=False), report["report_id"]),
            )
            connection.commit()
        finally:
            connection.close()
        return report

    def get_report(self, report_id):
        connection = get_connection()
        try:
            row = connection.execute(
                "SELECT report_json FROM generated_reports WHERE id = ?",
                (report_id,),
            ).fetchone()
            if row is None:
                raise KeyError(f"Report {report_id} was not found.")
            return json.loads(row["report_json"])
        finally:
            connection.close()
