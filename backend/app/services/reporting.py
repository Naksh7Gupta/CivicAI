"""Evidence-grounded incident, area, and executive report generation."""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from urllib.error import URLError
from urllib.request import Request, urlopen

from app.database.repository import (
    get_area_report_context,
    get_incident_report_context,
)


SYSTEM_PROMPT = """You write cautious civic infrastructure summaries from structured database facts.
Use only the supplied facts. Evidence URLs are references to stored files; you have not opened
or visually inspected those files, so do not describe their contents. Do not invent or estimate
coordinates, addresses, road names, measurements, physical severity, causes, inspection findings,
repair status, costs, or actions by municipal authorities. Model confidence is not physical severity.
A GPS fix is the camera or vehicle position associated with a frame, not the exact pothole position
unless the facts explicitly say otherwise. first_seen/last_seen are database ingestion times, not
original camera capture times; video_timestamp_seconds is relative to the media timeline. Clearly
label simulated coordinates. State when information is missing. Recommendations must be suggestions
for human field verification, never claims that an authority has acted. Return concise plain text only."""


class ReportGenerator:
    def __init__(self, *, base_url=None, api_key=None, model=None, timeout_seconds=20):
        self.base_url = base_url if base_url is not None else os.getenv("LLM_API_BASE_URL", "").strip()
        self.api_key = api_key if api_key is not None else os.getenv("LLM_API_KEY", "").strip()
        self.model = model if model is not None else os.getenv("LLM_MODEL", "").strip()
        self.timeout_seconds = timeout_seconds

    def generate_incident_report(self, incident_id):
        facts = get_incident_report_context(incident_id)
        if facts is None:
            raise LookupError(f"Incident {incident_id} was not found.")
        return self._generate("incident", facts)

    def generate_area_report(self, session_id=None):
        facts = get_area_report_context(session_id)
        return self._generate("area", facts)

    def generate_executive_summary(self, session_id=None):
        facts = get_area_report_context(session_id)
        return self._generate("executive_summary", facts)

    def _generate(self, report_type, facts):
        narrative = self._call_llm(report_type, facts)
        if narrative:
            source = "llm"
            llm_status = "generated"
        else:
            narrative = self._fallback_narrative(report_type, facts)
            source = "deterministic_fallback"
            llm_status = "not_configured_or_unavailable"
        return {
            "report_type": report_type,
            "facts": facts,
            "narrative": narrative,
            "narrative_source": source,
            "llm_status": llm_status,
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "disclaimer": (
                "The facts object is sourced from CivicAI's database. The narrative is an "
                "AI-generated interpretation or deterministic fallback and requires human review."
            ),
        }

    def _call_llm(self, report_type, facts):
        if not self.base_url or not self.model:
            return None
        payload = {
            "model": self.model,
            "temperature": 0.2,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": (
                        f"Create a {report_type} report from these database facts. "
                        "Do not add fields or claims not present in the facts.\n"
                        + json.dumps(facts, ensure_ascii=False, default=str)
                    ),
                },
            ],
        }
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        request = Request(
            self.base_url,
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                body = json.loads(response.read().decode("utf-8"))
            content = body["choices"][0]["message"]["content"]
            if isinstance(content, str) and content.strip():
                return content.strip()[:5000]
        except (OSError, URLError, TimeoutError, ValueError, KeyError, IndexError, TypeError):
            return None
        return None

    @staticmethod
    def _location_text(facts):
        latitude = facts.get("latitude")
        longitude = facts.get("longitude")
        if latitude is None or longitude is None:
            return "No GPS coordinate was associated with this incident."
        source = facts.get("location_source") or "unspecified source"
        if facts.get("is_simulated"):
            label = "SIMULATED coordinates"
        else:
            label = "GPS-associated camera/vehicle position estimate"
        accuracy = facts.get("gps_accuracy_m")
        accuracy_text = f"; reported accuracy {accuracy} m" if accuracy is not None else "; accuracy not supplied"
        status = facts.get("location_status") or "unknown status"
        delta = facts.get("gps_delta_seconds")
        delta_text = f"; GPS sample offset {delta} s" if delta is not None else ""
        return (
            f"{label}: {latitude}, {longitude} (source: {source}; status: {status}"
            f"{accuracy_text}{delta_text}). This is not a surveyed pothole coordinate."
        )

    def _fallback_narrative(self, report_type, facts):
        if report_type == "incident":
            observations = facts.get("observation_count", 0)
            tracks = facts.get("track_count", 0)
            confidence = facts.get("best_confidence")
            confidence_text = (
                f"Best recorded model confidence: {confidence:.3f}. "
                if isinstance(confidence, (int, float))
                else "Model confidence is unavailable. "
            )
            evidence = facts.get("evidence_count", 0)
            return (
                f"Incident {facts.get('id')} contains {observations} recorded model observation(s) "
                f"across {tracks} tracking record(s). {confidence_text}"
                f"Evidence image(s) stored: {evidence}. {self._location_text(facts)} "
                "Physical severity, pothole dimensions, road name, field inspection, and repair "
                "status are not established by these records. Model confidence must not be "
                "interpreted as damage severity. Human field verification is recommended."
            )

        count = facts.get("incident_count", 0) or 0
        observations = facts.get("observation_count", 0) or 0
        located = facts.get("located_incident_count", 0) or 0
        simulated = facts.get("simulated_location_count", 0) or 0
        evidence = facts.get("evidence_count", 0) or 0
        scope = facts.get("session_id") or "all recorded sessions"
        return (
            f"CivicAI database summary for {scope}: {count} incident record(s), "
            f"{observations} model observation(s), and {evidence} stored evidence image(s). "
            f"Coordinates are present for {located} incident record(s); {simulated} record(s) "
            "are explicitly marked as simulated. No physical severity, repair completion, or "
            "municipal response is inferred. Records should be reviewed by a human inspector."
        )
