"""Citizen complaint listing and tracking endpoints."""

from __future__ import annotations

import re
import sqlite3

from flask import Blueprint, current_app, request

from app.services.complaint_repository import hash_tracking_code

complaints_api = Blueprint("complaints_api", __name__)
_TRACKING_CODE_PATTERN = re.compile(r"^[A-Za-z0-9_-]{32,128}$")


@complaints_api.after_request
def prevent_complaint_caching(response):
    response.headers["Cache-Control"] = "no-store"
    return response


def _error(code: str, message: str, status: int):
    return {"error": {"code": code, "message": message}}, status


def _tracking_hash():
    authorization = request.headers.get("Authorization", "")
    scheme, separator, code = authorization.partition(" ")
    if not separator or scheme.casefold() != "bearer":
        return None
    code = code.strip()
    if not _TRACKING_CODE_PATTERN.fullmatch(code):
        return None
    return hash_tracking_code(code)


def _repository():
    return current_app.extensions["civicflow_complaints"]


def _public_history(history: list[dict[str, object]]) -> list[dict[str, object]]:
    return [
        {**entry, "updated_by": "CivicFlow administrator"}
        for entry in history
    ]


def _database_error():
    current_app.logger.exception("Complaint database read failed.")
    return _error("COMPLAINT_STORAGE_ERROR", "Complaint information is temporarily unavailable.", 503)


@complaints_api.get("/complaints")
def list_citizen_complaints():
    token_hash = _tracking_hash()
    if token_hash is None:
        return _error("TRACKING_CODE_REQUIRED", "Provide your private tracking code.", 401)
    try:
        return {"complaints": _repository().list_for_citizen(token_hash)}
    except sqlite3.Error:
        return _database_error()


@complaints_api.get("/complaints/<complaint_id>")
def get_citizen_complaint(complaint_id: str):
    token_hash = _tracking_hash()
    if token_hash is None:
        return _error("TRACKING_CODE_REQUIRED", "Provide your private tracking code.", 401)
    try:
        complaint = _repository().get_for_citizen(complaint_id, token_hash)
        if complaint is None:
            return _error("COMPLAINT_NOT_FOUND", "The complaint was not found.", 404)
        history = _repository().history(complaint_id)
        return {**complaint, "history": _public_history(history or [])}
    except sqlite3.Error:
        return _database_error()


@complaints_api.get("/complaints/<complaint_id>/status")
def get_citizen_complaint_status(complaint_id: str):
    token_hash = _tracking_hash()
    if token_hash is None:
        return _error("TRACKING_CODE_REQUIRED", "Provide your private tracking code.", 401)
    try:
        complaint = _repository().get_for_citizen(complaint_id, token_hash)
        if complaint is None:
            return _error("COMPLAINT_NOT_FOUND", "The complaint was not found.", 404)
        return {
            "complaint_id": complaint["complaint_id"],
            "status": complaint["status"],
            "last_updated_at": complaint["last_updated_at"],
        }
    except sqlite3.Error:
        return _database_error()


@complaints_api.get("/complaints/<complaint_id>/history")
def get_citizen_complaint_history(complaint_id: str):
    token_hash = _tracking_hash()
    if token_hash is None:
        return _error("TRACKING_CODE_REQUIRED", "Provide your private tracking code.", 401)
    try:
        complaint = _repository().get_for_citizen(complaint_id, token_hash)
        if complaint is None:
            return _error("COMPLAINT_NOT_FOUND", "The complaint was not found.", 404)
        history = _repository().history(complaint_id) or []
        return {"complaint_id": complaint_id, "history": _public_history(history)}
    except sqlite3.Error:
        return _database_error()
