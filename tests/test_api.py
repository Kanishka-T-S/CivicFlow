"""Flask API tests using fake speech transcription."""

from __future__ import annotations

import io
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import create_app  # noqa: E402
from app.config import Settings  # noqa: E402
from app.integrations.gnani_stt import TranscriptResult  # noqa: E402


class FakeSTT:
    def __init__(self, transcript="There is a pothole on Main Street."):
        self.transcript = transcript
        self.calls = []

    def transcribe(self, audio, **kwargs):
        self.calls.append((audio, kwargs))
        return TranscriptResult(transcript=self.transcript)


class CivicFlowAPITests(unittest.TestCase):
    def setUp(self):
        self.stt = FakeSTT()
        settings = Settings("", None, "en-IN", None, 10_000)
        self.app = create_app(settings, stt_client=self.stt)
        self.app.config["TESTING"] = True
        self.client = self.app.test_client()

    def test_homepage_renders_audio_request_flow(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/html", response.content_type)
        page = response.get_data(as_text=True)
        self.assertIn("CivicFlow", page)
        self.assertIn('id="audio-file"', page)
        self.assertIn('accept=".m4a,.mp3,.wav', page)
        self.assertIn("Transcribe &amp; continue", page)
        self.assertIn('id="transcript-text"', page)
        self.assertIn('id="confirm-request"', page)
        self.assertIn("/static/js/homepage.js", page)

    def test_homepage_assets_are_served(self):
        with self.client.get("/static/css/site.css") as css:
            self.assertEqual(css.status_code, 200)
            self.assertIn("text/css", css.content_type)
            self.assertIn(b".request-card", css.get_data())
        with self.client.get("/static/js/homepage.js") as script:
            self.assertEqual(script.status_code, 200)
            self.assertIn("javascript", script.content_type)
            script_text = script.get_data(as_text=True)
            self.assertIn("/api/v1/requests", script_text)
            self.assertIn("/messages", script_text)
            self.assertIn("/confirm", script_text)

    def test_audio_request_and_confirmation_workflow(self):
        response = self.client.post(
            "/api/v1/requests",
            data={"audio": (io.BytesIO(b"audio bytes"), "clip.m4a")},
            content_type="multipart/form-data",
        )
        self.assertEqual(response.status_code, 201)
        result = response.get_json()
        self.assertEqual(result["status"], "needs_details")
        self.assertIn("location", result["question"].lower())
        self.assertEqual(result["transcript"], self.stt.transcript)
        request_id = result["request_id"]

        response = self.client.post(
            f"/api/v1/requests/{request_id}/messages",
            json={"text": "Main Street"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["status"], "ready_for_confirmation")

        response = self.client.post(f"/api/v1/requests/{request_id}/confirm")
        self.assertEqual(response.status_code, 200)
        self.assertIn("has not been submitted", response.get_json()["message"])

    def test_unsupported_upload_is_rejected_before_stt(self):
        response = self.client.post(
            "/api/v1/requests",
            data={"audio": (io.BytesIO(b"video bytes"), "clip.mp4")},
            content_type="multipart/form-data",
        )
        self.assertEqual(response.status_code, 415)
        self.assertEqual(self.stt.calls, [])

    def test_followup_requires_valid_json_text(self):
        response = self.client.post(
            "/api/v1/requests/unknown/messages",
            json={"text": "   "},
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()["error"]["code"], "INVALID_MESSAGE")

    def test_confirming_incomplete_request_is_rejected(self):
        created = self.client.post(
            "/api/v1/requests",
            data={"audio": (io.BytesIO(b"audio bytes"), "clip.m4a")},
            content_type="multipart/form-data",
        ).get_json()
        response = self.client.post(f"/api/v1/requests/{created['request_id']}/confirm")
        self.assertEqual(response.status_code, 409)


if __name__ == "__main__":
    unittest.main()
