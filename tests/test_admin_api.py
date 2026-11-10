"""Administrator authentication and complaint-management tests."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from werkzeug.security import generate_password_hash  # noqa: E402

from app import create_app  # noqa: E402
from app.config import Settings  # noqa: E402
from app.services.complaint_repository import hash_tracking_code  # noqa: E402


class AdminAPITests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        settings = Settings(
            gnani_api_key="",
            stt_model=None,
            stt_language="en-IN",
            stt_format=None,
            database_path=str(Path(self.temp_dir.name) / "complaints.sqlite3"),
            secret_key="test-session-secret-value-at-least-32",
            admin_username="civic-admin",
            admin_password_hash=generate_password_hash(
                "test-admin-password", method="pbkdf2:sha256"
            ),
        )
        self.app = create_app(settings, stt_client=object())
        self.app.config["TESTING"] = True
        self.client = self.app.test_client()
        self.complaint, _created = self.app.extensions[
            "civicflow_complaints"
        ].register(
            source_request_id="admin-test-request",
            citizen_token_hash=hash_tracking_code("test-citizen-code"),
            category="Road Damage",
            description="Pothole on Main Street",
            location="Main Street",
        )

    def tearDown(self):
        self.temp_dir.cleanup()

    def csrf_token(self):
        response = self.client.get("/api/v1/admin/csrf")
        self.assertEqual(response.status_code, 200)
        return response.get_json()["csrf_token"]

    def login(self):
        csrf = self.csrf_token()
        response = self.client.post(
            "/api/v1/admin/login",
            json={"username": "civic-admin", "password": "test-admin-password"},
            headers={"X-CSRF-Token": csrf},
        )
        self.assertEqual(response.status_code, 200)
        return response.get_json()["csrf_token"]

    def test_admin_routes_reject_unauthorized_access(self):
        self.assertEqual(self.client.get("/admin").status_code, 302)
        response = self.client.get("/api/v1/admin/complaints")
        self.assertEqual(response.status_code, 401)
        self.assertEqual(
            response.get_json()["error"]["code"], "ADMIN_AUTH_REQUIRED"
        )
        self.assertEqual(response.headers["Cache-Control"], "no-store")

    def test_admin_login_requires_csrf_and_valid_credentials(self):
        csrf = self.csrf_token()
        missing_csrf = self.client.post(
            "/api/v1/admin/login",
            json={"username": "civic-admin", "password": "test-admin-password"},
        )
        self.assertEqual(missing_csrf.status_code, 400)

        invalid_login = self.client.post(
            "/api/v1/admin/login",
            json={"username": "civic-admin", "password": "incorrect"},
            headers={"X-CSRF-Token": csrf},
        )
        self.assertEqual(invalid_login.status_code, 401)

        csrf = self.csrf_token()
        valid_login = self.client.post(
            "/api/v1/admin/login",
            json={"username": "civic-admin", "password": "test-admin-password"},
            headers={"X-CSRF-Token": csrf},
        )
        self.assertEqual(valid_login.status_code, 200)
        self.assertTrue(valid_login.get_json()["authenticated"])

    def test_admin_can_filter_view_and_update_with_history(self):
        csrf = self.login()

        listing = self.client.get(
            "/api/v1/admin/complaints?category=Road+Damage&status=Pending"
        )
        self.assertEqual(listing.status_code, 200)
        self.assertEqual(
            listing.get_json()["complaints"][0]["complaint_id"],
            self.complaint["complaint_id"],
        )
        detail = self.client.get(
            f"/api/v1/admin/complaints/{self.complaint['complaint_id']}"
        )
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(len(detail.get_json()["history"]), 1)

        no_csrf = self.client.patch(
            f"/api/v1/admin/complaints/{self.complaint['complaint_id']}/status",
            json={"status": "In Progress", "remarks": "Assigned"},
        )
        self.assertEqual(no_csrf.status_code, 400)

        invalid_status = self.client.patch(
            f"/api/v1/admin/complaints/{self.complaint['complaint_id']}/status",
            json={"status": "Unknown", "remarks": ""},
            headers={"X-CSRF-Token": csrf},
        )
        self.assertEqual(invalid_status.status_code, 400)

        updated = self.client.patch(
            f"/api/v1/admin/complaints/{self.complaint['complaint_id']}/status",
            json={"status": "In Progress", "remarks": "Assigned to field team"},
            headers={"X-CSRF-Token": csrf},
        )
        self.assertEqual(updated.status_code, 200)
        self.assertEqual(updated.get_json()["status"], "In Progress")

        detail = self.client.get(
            f"/api/v1/admin/complaints/{self.complaint['complaint_id']}"
        ).get_json()
        self.assertEqual(
            [update["new_status"] for update in detail["history"]],
            ["Pending", "In Progress"],
        )
        self.assertEqual(detail["history"][-1]["remarks"], "Assigned to field team")

    def test_invalid_complaint_and_filter_values_are_rejected(self):
        self.login()
        self.assertEqual(
            self.client.get("/api/v1/admin/complaints/invalid-id").status_code, 404
        )
        self.assertEqual(
            self.client.get("/api/v1/admin/complaints?status=unknown").status_code, 400
        )

    def test_admin_html_dashboard_and_csrf_protected_status_form(self):
        self.login()
        dashboard = self.client.get("/admin")
        self.assertEqual(dashboard.status_code, 200)
        self.assertIn("Complaint management", dashboard.get_data(as_text=True))
        detail = self.client.get(
            f"/admin/complaints/{self.complaint['complaint_id']}"
        )
        self.assertEqual(detail.status_code, 200)
        missing = self.client.get("/admin/complaints/invalid-id")
        self.assertEqual(missing.status_code, 404)
        csrf = self.client.get("/api/v1/admin/csrf").get_json()["csrf_token"]
        update = self.client.post(
            f"/admin/complaints/{self.complaint['complaint_id']}/status",
            data={
                "csrf_token": csrf,
                "status": "Resolved",
                "remarks": "Issue fixed",
            },
            follow_redirects=True,
        )
        self.assertEqual(update.status_code, 200)
        self.assertIn("were saved", update.get_data(as_text=True))


if __name__ == "__main__":
    unittest.main()
