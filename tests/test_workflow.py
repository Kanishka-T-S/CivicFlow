"""Request workflow lifecycle tests."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.request_assessor import LocalRequestAssessor  # noqa: E402
from app.services.request_workflow import RequestNotFoundError, RequestWorkflow  # noqa: E402


class RequestWorkflowTests(unittest.TestCase):
    def test_expired_request_is_removed(self):
        workflow = RequestWorkflow(LocalRequestAssessor())
        with patch("app.services.request_workflow.time.monotonic", side_effect=[100, 100, 1901]):
            session = workflow.start("Pothole on Main Street.")
            with self.assertRaises(RequestNotFoundError):
                workflow.get(session.request_id)


if __name__ == "__main__":
    unittest.main()
