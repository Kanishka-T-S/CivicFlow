"""Tests for local civic-request classification and intake."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.request_assessor import LocalRequestAssessor  # noqa: E402


class LocalRequestAssessorTests(unittest.TestCase):
    def setUp(self):
        self.assessor = LocalRequestAssessor()

    def test_classifies_english_transcript_and_requests_location(self):
        result = self.assessor.assess("There is a large pothole on our street.")
        self.assertEqual(result.category, "roads")
        self.assertEqual(result.details["description"], "There is a large pothole on our street.")
        self.assertEqual(result.missing_fields, ("location",))
        self.assertTrue(result.question)

    def test_classifies_tamil_keywords(self):
        result = self.assessor.assess("எங்கள் தெருவில் பெரிய பள்ளம் உள்ளது")
        self.assertEqual(result.category, "roads")

    def test_followup_adds_location_without_changing_original_description(self):
        initial = self.assessor.assess("There is a pothole on our street.")
        result = self.assessor.assess(
            "Main Street near the library",
            {
                "category": initial.category,
                "summary": initial.summary,
                "details": initial.details,
            },
        )
        self.assertEqual(result.details["description"], initial.details["description"])
        self.assertEqual(result.details["location"], "Main Street near the library")
        self.assertEqual(result.missing_fields, ())
        self.assertTrue(result.ready_for_confirmation)

    def test_unknown_request_is_not_misclassified(self):
        result = self.assessor.assess("Please help with a public service request.")
        self.assertEqual(result.category, "other")


if __name__ == "__main__":
    unittest.main()
