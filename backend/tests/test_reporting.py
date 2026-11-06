import unittest
from unittest.mock import patch

from app.services.reporting import ReportGenerator


class ReportingTests(unittest.TestCase):
    def test_incident_fallback_labels_simulated_location_and_missing_severity(self):
        facts = {
            "id": 7,
            "observation_count": 4,
            "track_count": 1,
            "best_confidence": 0.91,
            "evidence_count": 1,
            "latitude": 0.1,
            "longitude": 0.2,
            "location_source": "synthetic",
            "is_simulated": True,
            "gps_accuracy_m": 3.0,
        }
        generator = ReportGenerator(base_url="", model="")
        with patch("app.services.reporting.get_incident_report_context", return_value=facts):
            report = generator.generate_incident_report(7)
        self.assertEqual(report["narrative_source"], "deterministic_fallback")
        self.assertIn("SIMULATED coordinates", report["narrative"])
        self.assertIn("must not be interpreted as damage severity", report["narrative"].lower())
        self.assertNotIn("High severity", report["narrative"])

    def test_llm_is_not_called_without_endpoint_or_model(self):
        generator = ReportGenerator(base_url="", model="")
        self.assertIsNone(generator._call_llm("incident", {"id": 1}))


if __name__ == "__main__":
    unittest.main()
