"""Versioned CivicFlow API routes."""

from __future__ import annotations

from pathlib import Path

from flask import Blueprint, current_app, request

from app.integrations.gnani_stt import SUPPORTED_EXTENSIONS, GnaniSTTError
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


def _workflow() -> RequestWorkflow:
    return current_app.extensions["civicflow_workflow"]


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
    try:
        session = _workflow().confirm(request_id)
    except RequestNotFoundError:
        return _error("REQUEST_NOT_FOUND", "The request was not found or has expired.", 404)
    except WorkflowStateError as exc:
        return _error("INVALID_WORKFLOW_STATE", str(exc), 409)
    return {
        **session.to_dict(),
        "message": "Request confirmed locally; it has not been submitted to a public authority.",
    }
