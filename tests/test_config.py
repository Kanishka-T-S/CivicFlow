"""Environment configuration tests for database and administrator settings."""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import ROOT_DIR, load_settings  # noqa: E402


class ConfigurationTests(unittest.TestCase):
    def test_phase_two_environment_settings_are_loaded_without_defaults_as_secrets(self):
        variables = {
            "GNANI_API_KEY": "test-key-not-a-real-secret",
            "CIVICFLOW_DATABASE_PATH": "storage/test.sqlite3",
            "CIVICFLOW_SECRET_KEY": "test-session-secret-value-at-least-32",
            "CIVICFLOW_ADMIN_USERNAME": "test-admin",
            "CIVICFLOW_ADMIN_PASSWORD_HASH": "test-password-hash",
            "CIVICFLOW_COOKIE_SECURE": "true",
        }
        with patch.dict(os.environ, variables, clear=True):
            settings = load_settings()

        self.assertEqual(settings.gnani_api_key, variables["GNANI_API_KEY"])
        self.assertEqual(
            settings.database_path,
            str(ROOT_DIR / "storage" / "test.sqlite3"),
        )
        self.assertEqual(settings.secret_key, variables["CIVICFLOW_SECRET_KEY"])
        self.assertEqual(settings.admin_username, "test-admin")
        self.assertEqual(settings.admin_password_hash, "test-password-hash")
        self.assertTrue(settings.session_cookie_secure)


if __name__ == "__main__":
    unittest.main()
