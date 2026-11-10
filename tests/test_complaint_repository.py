"""Persistence tests for the SQLite complaint repository."""

from __future__ import annotations

import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.complaint_repository import ComplaintRepository, hash_tracking_code  # noqa: E402


class ComplaintRepositoryTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temp_dir.name) / "complaints.sqlite3"
        self.repository = ComplaintRepository(self.database_path)

    def tearDown(self):
        self.temp_dir.cleanup()

    def register(self, source_request_id="request-1", location="Main Street"):
        return self.repository.register(
            source_request_id=source_request_id,
            citizen_token_hash=hash_tracking_code("private-code"),
            category="Road Damage",
            description="Pothole on the road",
            location=location,
        )

    def test_registration_persists_unique_complaint_and_initial_history(self):
        complaint, created = self.register()

        self.assertTrue(created)
        self.assertRegex(complaint["complaint_id"], r"^CF-[A-F0-9]{16}$")
        self.assertEqual(complaint["status"], "Pending")
        self.assertEqual(complaint["location"], "Main Street")

        reloaded = ComplaintRepository(self.database_path)
        self.assertEqual(reloaded.get(complaint["complaint_id"]), complaint)
        self.assertEqual(
            reloaded.history(complaint["complaint_id"])[0]["new_status"],
            "Pending",
        )

    def test_registration_is_idempotent_for_source_request(self):
        first, created = self.register()
        duplicate, duplicate_created = self.register(location="Different location")

        self.assertTrue(created)
        self.assertFalse(duplicate_created)
        self.assertEqual(first["complaint_id"], duplicate["complaint_id"])
        self.assertEqual(duplicate["location"], "Main Street")
        self.assertEqual(len(self.repository.list_all()), 1)

    def test_distinct_workflows_receive_distinct_complaint_ids(self):
        first, _created = self.register(source_request_id="request-first")
        second, _created = self.register(source_request_id="request-second")

        self.assertNotEqual(first["complaint_id"], second["complaint_id"])

    def test_citizen_token_scopes_listing_and_detail(self):
        complaint, _ = self.register()

        self.assertEqual(
            self.repository.list_for_citizen(hash_tracking_code("private-code")),
            [complaint],
        )
        self.assertEqual(
            self.repository.get_for_citizen(
                complaint["complaint_id"], hash_tracking_code("wrong-code")
            ),
            None,
        )

    def test_database_stores_only_the_tracking_code_hash(self):
        self.register()
        connection = sqlite3.connect(self.database_path)
        try:
            stored_hash = connection.execute(
                "SELECT citizen_token_hash FROM complaints"
            ).fetchone()[0]
        finally:
            connection.close()

        self.assertEqual(stored_hash, hash_tracking_code("private-code"))
        self.assertNotEqual(stored_hash, "private-code")

    def test_status_changes_are_append_only_and_chronological(self):
        complaint, _ = self.register()
        self.repository.update_status(
            complaint_id=complaint["complaint_id"],
            new_status="In Progress",
            remarks="Assigned to field team",
            updated_by="admin",
        )
        updated = self.repository.update_status(
            complaint_id=complaint["complaint_id"],
            new_status="Resolved",
            remarks="Repair completed",
            updated_by="admin",
        )

        history = self.repository.history(complaint["complaint_id"])
        self.assertEqual(updated["status"], "Resolved")
        self.assertEqual(
            [item["new_status"] for item in history],
            ["Pending", "In Progress", "Resolved"],
        )
        self.assertEqual(history[1]["previous_status"], "Pending")
        self.assertEqual(history[2]["remarks"], "Repair completed")
        self.assertEqual(history, sorted(history, key=lambda item: item["updated_at"]))
        reloaded = ComplaintRepository(self.database_path)
        self.assertEqual(
            len(reloaded.history(complaint["complaint_id"])),
            3,
        )

    def test_admin_search_and_filters_are_parameterized(self):
        self.register()
        self.assertEqual(
            self.repository.list_all(search="CF-", category="Road Damage", status="Pending"),
            self.repository.list_all(),
        )
        self.assertEqual(self.repository.list_all(search="' OR 1=1 --"), [])

    def test_shared_in_memory_database_persists_between_repository_connections(self):
        repository = ComplaintRepository(":memory:")
        complaint, _created = repository.register(
            source_request_id="memory-request",
            citizen_token_hash=hash_tracking_code("memory-code"),
            category="Other",
            description="A memory database request",
            location="Anywhere",
        )

        self.assertEqual(repository.get(complaint["complaint_id"]), complaint)


if __name__ == "__main__":
    unittest.main()
