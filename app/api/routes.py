"""Versioned CivicFlow API routes."""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path

from flask import Blueprint, current_app, request

from app.integrations.gnani_stt import SUPPORTED_EXTENSIONS, GnaniSTTError
from app.services.complaint_repository import (
    hash_tracking_code,
    new_tracking_code,
)
from app.services.request_workflow import (
    RequestNotFoundError,
    RequestWorkflow,
    WorkflowCapacityError,
    WorkflowStateError,
)

api = Blueprint("api", __name__)
_LOCAL_AUDIO_ERRORS = {
    "EMPTY_AUDIO",
    "MAX_AUDIO_DURATION_EXCEEDED",
    "UNSUPPORTED_AUDIO_FORMAT",
}
_TRACKING_CODE_PATTERN = re.compile(r"^[A-Za-z0-9_-]{32,128}$")


@api.after_request
def prevent_sensitive_api_caching(response):
    response.headers["Cache-Control"] = "no-store"
    return response


def _workflow() -> RequestWorkflow:
    return current_app.extensions["civicflow_workflow"]


def _complaint_category(category: str, description: str) -> str:
    normalized = description.casefold()
    if any(
        term in normalized
        for term in ("streetlight", "street light", "தெரு விளக்கு", "விளக்கு")
    ):
        return "Street Light"
    if any(term in normalized for term in ("electricity", "power outage", "மின்சாரம்")):
        return "Electricity"
    if any(term in normalized for term in ("drain", "sewage", "கழிவுநீர்")):
        return "Drainage"
    if category == "roads":
        return "Road Damage"
    if category == "water":
        return "Water Supply"
    if category == "waste":
        return "Garbage Collection"
    if category == "sanitation":
        return "Public Sanitation"
    if category == "utilities":
        return "Electricity"
    return "Other"


def _confirmed_response(session, *, status: int = 200):
    try:
        complaint = current_app.extensions["civicflow_complaints"].get(
            session.complaint_id
        )
    except sqlite3.Error:
        current_app.logger.exception("Complaint retrieval failed.")
        return _error("COMPLAINT_STORAGE_ERROR", "The complaint could not be loaded.", 503)
    if complaint is None or session.tracking_code is None:
        return _error("COMPLAINT_UNAVAILABLE", "The complaint could not be loaded.", 503)
    return {
        **session.to_dict(),
        **complaint,
        "status": session.status,
        "workflow_status": session.status,
        "complaint_status": complaint["status"],
        "tracking_code": session.tracking_code,
        "message": (
            "Complaint registered successfully; it has not been submitted to a public "
            "authority. Keep the private tracking code to view it later."
        ),
    }, status


def _error(code: str, message: str, status: int):
    return {"error": {"code": code, "message": message}}, status


@api.post("/requests")
def create_request():
    audio_file = request.files.get("audio")
    if audio_file is None or not audio_file.filename:
        return _error("AUDIO_REQUIRED", "Upload an audio file in the 'audio' field.", 400)

    suffix = Path(audio_file.filename).suffix.lower()
    if suffix not in SUPPORTED_EXTENSIONS:
        return _error("UNSUPPORTED_AUDIO_FORMAT", "The uploaded audio format is not supported.", 415)
    audio = audio_file.read()
    if not audio:
        return _error("EMPTY_AUDIO", "The uploaded audio file is empty.", 400)

    try:
        transcript = current_app.extensions["civicflow_stt"].transcribe(
            audio,
            language_code=current_app.config["CIVICFLOW_SETTINGS"].stt_language,
            model=current_app.config["CIVICFLOW_SETTINGS"].stt_model,
            fmt=current_app.config["CIVICFLOW_SETTINGS"].stt_format,
            filename=f"upload{suffix}",
        )
    except GnaniSTTError as exc:
        current_app.logger.warning("Gnani transcription failed (%s).", exc.error_type or "unknown")
        status = 400 if exc.error_type in _LOCAL_AUDIO_ERRORS else 502
        return _error(exc.error_type or "STT_ERROR", "Audio transcription failed.", status)

    if transcript.is_empty:
        return _error("NO_SPEECH_DETECTED", "No speech was detected in the audio.", 422)

    try:
        session = _workflow().start(transcript.transcript)
    except WorkflowCapacityError:
        return _error("WORKFLOW_CAPACITY", "The service is temporarily at capacity. Try again later.", 503)
    return {"transcript": transcript.transcript, **session.to_dict()}, 201


@api.get("/requests/<request_id>")
def get_request(request_id: str):
    try:
        return _workflow().get(request_id).to_dict()
    except RequestNotFoundError:
        return _error("REQUEST_NOT_FOUND", "The request was not found or has expired.", 404)


@api.post("/requests/<request_id>/messages")
def add_message(request_id: str):
    if not request.is_json:
        return _error("JSON_REQUIRED", "Send a JSON object containing a 'text' field.", 415)
    payload = request.get_json()
    if not isinstance(payload, dict):
        return _error("INVALID_MESSAGE", "The request body must be a JSON object.", 400)
    text = payload.get("text")
    if not isinstance(text, str) or not text.strip() or len(text) > 4000:
        return _error("INVALID_MESSAGE", "The 'text' field must contain 1 to 4000 characters.", 400)

    try:
        session = _workflow().continue_request(request_id, text.strip())
    except RequestNotFoundError:
        return _error("REQUEST_NOT_FOUND", "The request was not found or has expired.", 404)
    except WorkflowStateError as exc:
        return _error("INVALID_WORKFLOW_STATE", str(exc), 409)
    return session.to_dict()


@api.post("/requests/<request_id>/confirm")
def confirm_request(request_id: str):
    workflow = _workflow()
    try:
        current_session = workflow.get(request_id)
    except RequestNotFoundError:
        return _error("REQUEST_NOT_FOUND", "The request was not found or has expired.", 404)

    if current_session.status == "confirmed" and current_session.complaint_id:
        return _confirmed_response(current_session)

    payload = request.get_json(silent=True) if request.is_json else {}
    if payload is None:
        payload = {}
    if not isinstance(payload, dict):
        return _error("INVALID_CONFIRMATION", "The request body must be a JSON object.", 400)
    supplied_code = payload.get("tracking_code")
    if supplied_code is not None and (
        not isinstance(supplied_code, str)
        or not _TRACKING_CODE_PATTERN.fullmatch(supplied_code)
    ):
        return _error("INVALID_TRACKING_CODE", "The tracking code is invalid.", 400)
    if supplied_code:
        try:
            known_code = current_app.extensions["civicflow_complaints"].has_citizen_token(
                hash_tracking_code(supplied_code)
            )
        except sqlite3.Error:
            current_app.logger.exception("Complaint tracking-code lookup failed.")
            return _error(
                "COMPLAINT_STORAGE_ERROR",
                "The complaint could not be saved. Try again.",
                503,
            )
        if not known_code:
            return _error(
                "INVALID_TRACKING_CODE",
                "The tracking code does not match an existing complaint.",
                401,
            )
    tracking_code = supplied_code or new_tracking_code()

    def register_complaint(session) -> None:
        details = session.assessment.details
        if (
            len(details["description"]) > 4000
            or len(details["location"]) > 4000
        ):
            raise ValueError("Complaint description and location must be 4000 characters or fewer.")
        complaint, _created = current_app.extensions["civicflow_complaints"].register(
            source_request_id=request_id,
            citizen_token_hash=hash_tracking_code(tracking_code),
            category=_complaint_category(
                session.assessment.category, details["description"]
            ),
            description=details["description"].strip(),
            location=details["location"].strip(),
        )
        session.complaint_id = str(complaint["complaint_id"])
        session.tracking_code = tracking_code

    try:
        session = workflow.confirm(request_id, before_confirm=register_complaint)
    except RequestNotFoundError:
        return _error("REQUEST_NOT_FOUND", "The request was not found or has expired.", 404)
    except WorkflowStateError as exc:
        try:
            current_session = workflow.get(request_id)
        except RequestNotFoundError:
            return _error("REQUEST_NOT_FOUND", "The request was not found or has expired.", 404)
        if current_session.status == "confirmed" and current_session.complaint_id:
            return _confirmed_response(current_session)
        return _error("INVALID_WORKFLOW_STATE", str(exc), 409)
    except ValueError as exc:
        return _error("INVALID_COMPLAINT_DETAILS", str(exc), 422)
    except sqlite3.Error:
        current_app.logger.exception("Complaint registration failed.")
        return _error("COMPLAINT_STORAGE_ERROR", "The complaint could not be saved. Try again.", 503)
    return _confirmed_response(session)
