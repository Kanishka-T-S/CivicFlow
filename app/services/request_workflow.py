"""Ephemeral, multi-turn public-service request intake workflow."""

from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from app.services.request_assessor import IntakeAssessment, LocalRequestAssessor


class RequestNotFoundError(Exception):
    """Raised when a workflow request does not exist in this process."""


class WorkflowStateError(Exception):
    """Raised when an operation is not valid for the workflow's current state."""


class WorkflowCapacityError(Exception):
    """Raised when the process-local workflow store has reached its limit."""


@dataclass
class RequestSession:
    request_id: str
    assessment: IntakeAssessment
    status: str
    expires_at: float
    lock: threading.RLock = field(default_factory=threading.RLock, repr=False)

    def to_dict(self) -> dict[str, Any]:
        with self.lock:
            return {
                "request_id": self.request_id,
                "status": self.status,
                "category": self.assessment.category,
                "summary": self.assessment.summary,
                "details": dict(self.assessment.details),
                "missing_fields": list(self.assessment.missing_fields),
                "question": self.assessment.question,
            }


class RequestWorkflow:
    _session_ttl_seconds = 30 * 60
    _max_sessions = 1000

    def __init__(self, assessor: LocalRequestAssessor) -> None:
        self._assessor = assessor
        self._sessions: dict[str, RequestSession] = {}
        self._lock = threading.RLock()

    def start(self, transcript: str) -> RequestSession:
        assessment = self._assessor.assess(transcript)
        session = RequestSession(
            request_id=uuid.uuid4().hex,
            assessment=assessment,
            status=self._status_for(assessment),
            expires_at=time.monotonic() + self._session_ttl_seconds,
        )
        with self._lock:
            self._remove_expired()
            if len(self._sessions) >= self._max_sessions:
                raise WorkflowCapacityError
            self._sessions[session.request_id] = session
        return session

    def get(self, request_id: str) -> RequestSession:
        return self._find(request_id)

    def _find(self, request_id: str) -> RequestSession:
        with self._lock:
            session = self._sessions.get(request_id)
            if session is None:
                raise RequestNotFoundError
        with session.lock:
            self._touch_session(session)
            return session

    def continue_request(self, request_id: str, message: str) -> RequestSession:
        session = self._find(request_id)
        with session.lock:
            self._touch_session(session)
            if session.status == "confirmed":
                raise WorkflowStateError("Confirmed requests cannot be changed.")

            context = {
                "category": session.assessment.category,
                "summary": session.assessment.summary,
                "details": session.assessment.details,
            }
            assessment = self._assessor.assess(message, context)
            session.assessment = assessment
            session.status = self._status_for(assessment)
            self._touch_session(session)
            return session

    def confirm(self, request_id: str) -> RequestSession:
        session = self._find(request_id)
        with session.lock:
            self._touch_session(session)
            if session.status != "ready_for_confirmation":
                raise WorkflowStateError("Request details must be complete before confirmation.")
            session.status = "confirmed"
            return session

    def _touch_session(self, session: RequestSession) -> None:
        with self._lock:
            if (
                self._sessions.get(session.request_id) is not session
                or session.expires_at <= time.monotonic()
            ):
                self._sessions.pop(session.request_id, None)
                raise RequestNotFoundError
            session.expires_at = time.monotonic() + self._session_ttl_seconds

    def _remove_expired(self) -> None:
        now = time.monotonic()
        expired = [
            request_id
            for request_id, session in self._sessions.items()
            if session.expires_at <= now
        ]
        for request_id in expired:
            self._sessions.pop(request_id, None)

    @staticmethod
    def _status_for(assessment: IntakeAssessment) -> str:
        return "ready_for_confirmation" if assessment.ready_for_confirmation else "needs_details"
