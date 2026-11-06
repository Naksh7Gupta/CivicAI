import unittest

from app.services.reporting import ReportValidationError, validate_llm_payload


class ReportValidationTests(unittest.TestCase):
    def test_accepts_only_known_evidence_references(self):
        payload = {
            "narrative": "A pothole candidate was recorded.",
            "narrative_evidence_ids": ["OBS-4"],
            "follow_up": [
                {"text": "Review the captured frame.", "evidence_ids": ["OBS-4"]}
            ],
        }
        result = validate_llm_payload(payload, ["OBS-4"])
        self.assertEqual(result["narrative_evidence_ids"], ["OBS-4"])

    def test_rejects_unknown_evidence_reference(self):
        payload = {
            "narrative": "A pothole candidate was recorded.",
            "narrative_evidence_ids": ["OBS-999"],
            "follow_up": [],
        }
        with self.assertRaises(ReportValidationError):
            validate_llm_payload(payload, ["OBS-4"])

    def test_requires_citations_for_follow_up(self):
        payload = {
            "narrative": "A pothole candidate was recorded.",
            "narrative_evidence_ids": ["OBS-4"],
            "follow_up": [{"text": "Inspect the site.", "evidence_ids": []}],
        }
        with self.assertRaises(ReportValidationError):
            validate_llm_payload(payload, ["OBS-4"])


if __name__ == "__main__":
    unittest.main()
