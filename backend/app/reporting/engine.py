"""Evidence-first report generation with an optional OpenAI-compatible LLM."""
import json
import os
import urllib.error
import urllib.request

from app.services.incident_repository import get_incident_evidence, list_incidents


SYSTEM_PROMPT = """You write cautious civic infrastructure summaries from supplied records.
Use only facts present in the JSON evidence. Never invent coordinates, addresses,
measurements, pothole depth, physical severity, cause, inspection results, repair
status, ownership, or actions taken by an authority. Detection confidence is not
physical severity and must not be described as severity. GPS describes the
recording vehicle/phone position, not an exact pothole point. If coordinates are
synthetic, explicitly say they are simulated. If GPS is absent, say the location
is unavailable. Keep suggested field checks clearly phrased as recommendations,
not completed actions. Return only valid JSON with exactly these keys:
{"summary": "...", "field_checks": ["..."]}."""


def _llm_config():
    return {
        "base_url": os.getenv("CIVICAI_LLM_BASE_URL", "https://api.openai.com/v1").rstrip("/"),
        "api_key": os.getenv("CIVICAI_LLM_API_KEY", "").strip(),
        "model": os.getenv("CIVICAI_LLM_MODEL", "").strip(),
        "timeout": float(os.getenv("CIVICAI_LLM_TIMEOUT_SECONDS", "25")),
    }


def _extract_message_content(payload: dict) -> str:
    choices = payload.get("choices") or []
    if not choices:
        raise ValueError("LLM response did not contain a completion choice.")
    message = choices[0].get("message") or {}
    content = message.get("content")
    if not isinstance(content, str) or not content.strip():
        raise ValueError("LLM response did not contain text content.")
    return content.strip()


def generate_narrative(evidence: dict) -> dict:
    config = _llm_config()
    if not config["api_key"] or not config["model"]:
        return {
            "status": "not_configured",
            "summary": None,
            "field_checks": [],
            "message": "Set CIVICAI_LLM_API_KEY and CIVICAI_LLM_MODEL to enable LLM narrative generation.",
        }

    allowed_evidence = {
        "id": evidence["id"],
        "issue_category": evidence["issue_category"],
        "timestamp_semantics": evidence.get(
            "timestamp_semantics", "processing time; not source-video capture time"
        ),
        "observation_count": evidence["observation_count"],
        "best_detection_confidence": evidence["best_detection_confidence"],
        "location": {
            "latitude": evidence["latitude"],
            "longitude": evidence["longitude"],
            "gps_accuracy_m": evidence["gps_accuracy_m"],
            "source": evidence["location_source"],
            "is_simulated": evidence["is_simulated"],
            "kind": evidence["location_kind"],
        },
        "observations": [
            {
                "observation_id": item["observation_id"],
                "timestamp": item["timestamp"],
                "detection_confidence": item["detection_confidence"],
                "gps_associated": item["gps_associated"],
            }
            for item in evidence["evidence"]
        ],
    }
    if "incident_track_count" in evidence:
        allowed_evidence["summary_counts"] = {
            key: evidence[key]
            for key in (
                "incident_track_count",
                "incidents_with_associated_vehicle_position",
                "real_gps_incidents",
                "simulated_gps_incidents",
                "incidents_without_gps",
            )
        }

    request_body = {
        "model": config["model"],
        "temperature": 0.1,
        "max_tokens": 450,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": json.dumps(allowed_evidence, ensure_ascii=False)},
        ],
    }
    request = urllib.request.Request(
        f"{config['base_url']}/chat/completions",
        data=json.dumps(request_body).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {config['api_key']}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=config["timeout"]) as response:
            raw = json.loads(response.read().decode("utf-8"))
        content = _extract_message_content(raw)
        parsed = json.loads(content)
        summary = parsed.get("summary")
        field_checks = parsed.get("field_checks")
        if not isinstance(summary, str) or not summary.strip() or len(summary) > 1600:
            raise ValueError("LLM summary was missing or exceeded the allowed length.")
        if not isinstance(field_checks, list) or len(field_checks) > 6:
            raise ValueError("LLM field_checks must be a list of at most six items.")
        if any(not isinstance(item, str) or not item.strip() or len(item) > 240 for item in field_checks):
            raise ValueError("LLM returned an invalid field check.")
        return {
            "status": "generated",
            "summary": summary.strip(),
            "field_checks": [item.strip() for item in field_checks],
            "message": None,
        }
    except (urllib.error.URLError, TimeoutError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        return {
            "status": "failed",
            "summary": None,
            "field_checks": [],
            "message": f"LLM report generation failed: {type(exc).__name__}.",
        }


def generate_incident_report(track_record_id: int) -> dict | None:
    evidence = get_incident_evidence(track_record_id)
    if evidence is None:
        return None
    narrative = generate_narrative(evidence)
    notices = []
    if evidence["latitude"] is None or evidence["longitude"] is None:
        notices.append("No GPS position could be associated with this incident.")
    else:
        notices.append(
            "Coordinates represent an estimated recording-vehicle position, not a surveyed pothole location."
        )
        if evidence["is_simulated"]:
            notices.append("GPS coordinates are simulated for demonstration and are not real-world measurements.")
    return {
        "report_type": "incident",
        "facts": evidence,
        "narrative": narrative,
        "notices": notices + [
            "The LLM narrative is advisory text; the structured database facts remain the source of truth."
        ],
        "severity": {"value": None, "status": "not_assessed"},
    }


def generate_session_summary(session_id: str | None = None) -> dict:
    incidents = list_incidents(session_id=session_id)
    total = len(incidents)
    located = [item for item in incidents if item["latitude"] is not None]
    real = [item for item in located if not item["is_simulated"]]
    simulated = [item for item in located if item["is_simulated"]]
    observation_count = sum(item["observation_count"] for item in incidents)
    summary_evidence = {
        "id": "SESSION-SUMMARY",
        "issue_category": "pothole_candidate_summary",
        "timestamp_semantics": "UTC processing time; not source-video capture time",
        "observation_count": observation_count,
        "best_detection_confidence": None,
        "latitude": None,
        "longitude": None,
        "gps_accuracy_m": None,
        "location_source": None,
        "is_simulated": False,
        "location_kind": None,
        "evidence": [],
        "incident_track_count": total,
        "incidents_with_associated_vehicle_position": len(located),
        "real_gps_incidents": len(real),
        "simulated_gps_incidents": len(simulated),
        "incidents_without_gps": total - len(located),
    }
    return {
        "report_type": "session_summary" if session_id else "database_summary",
        "session_id": session_id,
        "facts": {
            "incident_track_count": total,
            "observation_count": observation_count,
            "incidents_with_associated_vehicle_position": len(located),
            "real_gps_incidents": len(real),
            "simulated_gps_incidents": len(simulated),
            "incidents_without_gps": total - len(located),
            "severity_assessed_count": 0,
            "deduplication_scope": "same_session_tracker_track_only",
        },
        "narrative": generate_narrative(summary_evidence),
        "notices": [
            "Counts are based on tracker tracks; repeated observations within each track are aggregated.",
            "Cross-session duplicate matching is not performed because current GPS is a vehicle-position estimate, not a calibrated pothole coordinate.",
            "Physical severity is not assessed from detection confidence.",
        ],
    }
