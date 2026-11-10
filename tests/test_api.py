"""Flask API tests using fake speech transcription."""

from __future__ import annotations

import io
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import create_app  # noqa: E402
from app.config import Settings  # noqa: E402
from app.integrations.gnani_stt import TranscriptResult  # noqa: E402
from app.services.complaint_repository import hash_tracking_code  # noqa: E402


class FakeSTT:
    def __init__(self, transcript="There is a pothole on Main Street."):
        self.transcript = transcript
        self.calls = []

    def transcribe(self, audio, **kwargs):
        self.calls.append((audio, kwargs))
        return TranscriptResult(transcript=self.transcript)


class CivicFlowAPITests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.stt = FakeSTT()
        settings = Settings(
            "",
            None,
            "en-IN",
            None,
            10_000,
            database_path=str(Path(self.temp_dir.name) / "complaints.sqlite3"),
        )
        self.app = create_app(settings, stt_client=self.stt)
        self.app.config["TESTING"] = True
        self.client = self.app.test_client()

    def tearDown(self):
        self.temp_dir.cleanup()

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
        self.assertEqual(self.app.extensions["civicflow_complaints"].list_all(), [])
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
        self.assertRegex(response.get_json()["complaint_id"], r"^CF-[A-F0-9]{16}$")
        self.assertEqual(response.get_json()["status"], "confirmed")
        self.assertEqual(response.get_json()["complaint_status"], "Pending")
        self.assertEqual(len(self.app.extensions["civicflow_complaints"].list_all()), 1)

    def test_voice_confirmation_maps_specific_categories(self):
        examples = (
            ("A street light is out at the intersection.", "Street Light"),
            ("Sewage is overflowing from the drain.", "Drainage"),
            ("There is a power outage in the area.", "Electricity"),
            ("Garbage has not been collected.", "Garbage Collection"),
        )
        for transcript, expected_category in examples:
            with self.subTest(category=expected_category):
                self.stt.transcript = transcript
                created = self.client.post(
                    "/api/v1/requests",
                    data={"audio": (io.BytesIO(b"audio bytes"), "clip.m4a")},
                    content_type="multipart/form-data",
                ).get_json()
                request_id = created["request_id"]
                self.client.post(
                    f"/api/v1/requests/{request_id}/messages",
                    json={"text": "Test location"},
                )
                confirmed = self.client.post(
                    f"/api/v1/requests/{request_id}/confirm"
                ).get_json()
                self.assertEqual(confirmed["category"], expected_category)

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
        self.assertEqual(self.app.extensions["civicflow_complaints"].list_all(), [])

    def test_admin_access_is_disabled_without_environment_credentials(self):
        login_page = self.client.get("/admin/login")
        self.assertEqual(login_page.status_code, 200)
        self.assertIn("enable access", login_page.get_data(as_text=True).lower())
        self.assertEqual(self.client.get("/admin").status_code, 503)
        self.assertEqual(self.client.get("/api/v1/admin/complaints").status_code, 503)

    def test_repeated_confirmation_does_not_create_duplicate_complaints(self):
        created = self.client.post(
            "/api/v1/requests",
            data={"audio": (io.BytesIO(b"audio bytes"), "clip.m4a")},
            content_type="multipart/form-data",
        ).get_json()
        request_id = created["request_id"]
        self.client.post(
            f"/api/v1/requests/{request_id}/messages",
            json={"text": "Main Street"},
        )

        first = self.client.post(f"/api/v1/requests/{request_id}/confirm")
        repeated = self.client.post(f"/api/v1/requests/{request_id}/confirm")

        self.assertEqual(first.status_code, 200)
        self.assertEqual(repeated.status_code, 200)
        self.assertEqual(
            first.get_json()["complaint_id"], repeated.get_json()["complaint_id"]
        )
        self.assertEqual(
            first.get_json()["tracking_code"], repeated.get_json()["tracking_code"]
        )
        self.assertEqual(len(self.app.extensions["civicflow_complaints"].list_all()), 1)

    def test_existing_tracking_code_can_access_later_complaints(self):
        def submit(code=None):
            created = self.client.post(
                "/api/v1/requests",
                data={"audio": (io.BytesIO(b"audio bytes"), "clip.m4a")},
                content_type="multipart/form-data",
            ).get_json()
            request_id = created["request_id"]
            self.client.post(
                f"/api/v1/requests/{request_id}/messages",
                json={"text": "Main Street"},
            )
            payload = {"tracking_code": code} if code else {}
            response = self.client.post(
                f"/api/v1/requests/{request_id}/confirm", json=payload
            )
            self.assertEqual(response.status_code, 200)
            return response.get_json()

        first = submit()
        second = submit(first["tracking_code"])
        listing = self.client.get(
            "/api/v1/complaints",
            headers={"Authorization": f"Bearer {first['tracking_code']}"},
        )
        self.assertEqual(first["tracking_code"], second["tracking_code"])
        self.assertEqual(len(listing.get_json()["complaints"]), 2)

    def test_unrecognized_tracking_code_cannot_be_chosen_by_caller(self):
        created = self.client.post(
            "/api/v1/requests",
            data={"audio": (io.BytesIO(b"audio bytes"), "clip.m4a")},
            content_type="multipart/form-data",
        ).get_json()
        request_id = created["request_id"]
        self.client.post(
            f"/api/v1/requests/{request_id}/messages",
            json={"text": "Main Street"},
        )

        response = self.client.post(
            f"/api/v1/requests/{request_id}/confirm",
            json={"tracking_code": "a" * 43},
        )
        self.assertEqual(response.status_code, 401)
        self.assertEqual(len(self.app.extensions["civicflow_complaints"].list_all()), 0)

    def test_citizen_complaint_routes_require_the_private_tracking_code(self):
        created = self.client.post(
            "/api/v1/requests",
            data={"audio": (io.BytesIO(b"audio bytes"), "clip.m4a")},
            content_type="multipart/form-data",
        ).get_json()
        request_id = created["request_id"]
        self.client.post(
            f"/api/v1/requests/{request_id}/messages",
            json={"text": "Main Street"},
        )
        registered = self.client.post(
            f"/api/v1/requests/{request_id}/confirm"
        ).get_json()
        complaint_id = registered["complaint_id"]

        unauthorized = self.client.get("/api/v1/complaints")
        self.assertEqual(unauthorized.status_code, 401)
        self.assertEqual(
            self.client.get(
                f"/api/v1/complaints/{complaint_id}",
                headers={"Authorization": "Bearer " + "x" * 43},
            ).status_code,
            404,
        )

        headers = {"Authorization": f"Bearer {registered['tracking_code']}"}
        listing = self.client.get("/api/v1/complaints", headers=headers)
        detail = self.client.get(
            f"/api/v1/complaints/{complaint_id}", headers=headers
        )
        history = self.client.get(
            f"/api/v1/complaints/{complaint_id}/history", headers=headers
        )
        status = self.client.get(
            f"/api/v1/complaints/{complaint_id}/status", headers=headers
        )
        self.assertEqual(listing.status_code, 200)
        self.assertEqual(listing.headers["Cache-Control"], "no-store")
        self.assertEqual(len(listing.get_json()["complaints"]), 1)
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(detail.get_json()["location"], "Main Street")
        self.assertEqual(history.status_code, 200)
        self.assertEqual(history.get_json()["history"][0]["new_status"], "Pending")
        self.assertEqual(status.get_json()["status"], "Pending")

    def test_citizen_dashboard_renders(self):
        response = self.client.get("/complaints")

        self.assertEqual(response.status_code, 200)
        self.assertIn("Your complaint dashboard", response.get_data(as_text=True))
        self.assertIn("Forget code on this device", response.get_data(as_text=True))


if __name__ == "__main__":
    unittest.main()
