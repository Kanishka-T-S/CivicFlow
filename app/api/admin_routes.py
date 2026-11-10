"""Administrator pages and authenticated complaint-management API."""

from __future__ import annotations

import sqlite3
from functools import wraps
from typing import Callable

from flask import (
    Blueprint,
    current_app,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

from app.security.admin import (
    admin_auth_configured,
    authenticate_admin,
    csrf_token,
    valid_csrf_token,
)
from app.services.complaint_repository import COMPLAINT_CATEGORIES, COMPLAINT_STATUSES

admin_pages = Blueprint("admin_pages", __name__)
admin_api = Blueprint("admin_api", __name__)


@admin_pages.after_request
@admin_api.after_request
def prevent_admin_caching(response):
    response.headers["Cache-Control"] = "no-store"
    response.headers["Vary"] = "Cookie"
    return response


def _repository():
    return current_app.extensions["civicflow_complaints"]


def _admin_logged_in() -> bool:
    return session.get("admin_authenticated") is True


def _api_error(code: str, message: str, status: int):
    return jsonify({"error": {"code": code, "message": message}}), status


def _login_required(view: Callable):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not admin_auth_configured():
            return render_template(
                "admin_login.html",
                csrf_token=csrf_token(),
                error="Administrator authentication is not configured.",
                configuration_missing=True,
            ), 503
        if not _admin_logged_in():
            return redirect(url_for("admin_pages.login"))
        return view(*args, **kwargs)

    return wrapped


def _api_login_required(view: Callable):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not admin_auth_configured():
            return _api_error(
                "ADMIN_AUTH_NOT_CONFIGURED",
                "Administrator access is not configured.",
                503,
            )
        if not _admin_logged_in():
            return _api_error("ADMIN_AUTH_REQUIRED", "Administrator login is required.", 401)
        return view(*args, **kwargs)

    return wrapped


def _settings_error(message: str, status: int = 400):
    return render_template(
        "admin_login.html",
        csrf_token=csrf_token(),
        error=message,
        configuration_missing=not admin_auth_configured(),
    ), status


def _admin_page_error(message: str, status: int):
    return render_template("admin_error.html", error=message), status


@admin_pages.get("/login")
def login():
    return render_template(
        "admin_login.html",
        csrf_token=csrf_token(),
        error="",
        configuration_missing=not admin_auth_configured(),
    )


@admin_pages.post("/login")
def login_submit():
    if not valid_csrf_token(request.form.get("csrf_token")):
        return _settings_error("Your login form expired. Reload and try again.")
    if not admin_auth_configured():
        return _settings_error("Administrator authentication is not configured.", 503)
    if not authenticate_admin(
        request.form.get("username"), request.form.get("password")
    ):
        return _settings_error("The username or password is incorrect.", 401)
    session.clear()
    session["admin_authenticated"] = True
    session["admin_username"] = current_app.config[
        "CIVICFLOW_SETTINGS"
    ].admin_username
    csrf_token()
    session.permanent = True
    return redirect(url_for("admin_pages.dashboard"))


@admin_pages.get("")
@_login_required
def dashboard():
    search = request.args.get("search", "").strip()
    category = request.args.get("category", "").strip()
    status = request.args.get("status", "").strip()
    if len(search) > 80:
        return _admin_page_error("Search text must be 80 characters or fewer.", 400)
    if category and category not in COMPLAINT_CATEGORIES:
        return _admin_page_error("Choose a valid complaint category.", 400)
    if status and status not in COMPLAINT_STATUSES:
        return _admin_page_error("Choose a valid complaint status.", 400)
    try:
        complaints = _repository().list_all(
            search=search, category=category, status=status
        )
    except sqlite3.Error:
        current_app.logger.exception("Administrator complaint listing failed.")
        return _admin_page_error("Complaint information is temporarily unavailable.", 503)
    return render_template(
        "admin_dashboard.html",
        csrf_token=csrf_token(),
        complaints=complaints,
        complaint=None,
        history=[],
        categories=COMPLAINT_CATEGORIES,
        statuses=COMPLAINT_STATUSES,
        search=search,
        selected_category=category,
        selected_status=status,
        admin_username=session.get("admin_username", ""),
    )


@admin_pages.get("/complaints/<complaint_id>")
@_login_required
def complaint_detail(complaint_id: str):
    try:
        complaint = _repository().get(complaint_id)
        history = _repository().history(complaint_id)
    except sqlite3.Error:
        current_app.logger.exception("Administrator complaint retrieval failed.")
        return _admin_page_error("Complaint information is temporarily unavailable.", 503)
    if complaint is None or history is None:
        return render_template(
            "admin_not_found.html",
            csrf_token=csrf_token(),
            admin_username=session.get("admin_username", ""),
        ), 404
    return render_template(
        "admin_dashboard.html",
        csrf_token=csrf_token(),
        complaints=[],
        complaint=complaint,
        history=history,
        categories=COMPLAINT_CATEGORIES,
        statuses=COMPLAINT_STATUSES,
        search="",
        selected_category="",
        selected_status="",
        admin_username=session.get("admin_username", ""),
    )


@admin_pages.post("/complaints/<complaint_id>/status")
@_login_required
def update_complaint_status(complaint_id: str):
    if not valid_csrf_token(request.form.get("csrf_token")):
        return _admin_page_error("Your form expired. Reload and try again.", 400)
    new_status = request.form.get("status", "")
    remarks = request.form.get("remarks", "").strip()
    if new_status not in COMPLAINT_STATUSES:
        return _admin_page_error("Choose a valid complaint status.", 400)
    if len(remarks) > 2000:
        return _admin_page_error("Remarks must be 2000 characters or fewer.", 400)
    try:
        complaint = _repository().update_status(
            complaint_id=complaint_id,
            new_status=new_status,
            remarks=remarks,
            updated_by=str(session.get("admin_username", "admin")),
        )
    except sqlite3.Error:
        current_app.logger.exception("Administrator complaint update failed.")
        return _admin_page_error("The complaint could not be updated. Try again.", 503)
    if complaint is None:
        return render_template(
            "admin_not_found.html",
            csrf_token=csrf_token(),
            admin_username=session.get("admin_username", ""),
        ), 404
    flash("Complaint status and remarks were saved.", "success")
    return redirect(url_for("admin_pages.complaint_detail", complaint_id=complaint_id))


@admin_pages.post("/logout")
@_login_required
def logout():
    if not valid_csrf_token(request.form.get("csrf_token")):
        return _admin_page_error("Your form expired. Reload and try again.", 400)
    session.clear()
    return redirect(url_for("admin_pages.login"))


@admin_api.get("/csrf")
def get_csrf_token():
    return {"csrf_token": csrf_token()}


@admin_api.post("/login")
def api_login():
    if not valid_csrf_token(request.headers.get("X-CSRF-Token")):
        return _api_error("CSRF_VALIDATION_FAILED", "A valid CSRF token is required.", 400)
    if not admin_auth_configured():
        return _api_error(
            "ADMIN_AUTH_NOT_CONFIGURED",
            "Administrator access is not configured.",
            503,
        )
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict) or not authenticate_admin(
        payload.get("username"), payload.get("password")
    ):
        return _api_error("INVALID_CREDENTIALS", "The username or password is incorrect.", 401)
    session.clear()
    session["admin_authenticated"] = True
    session["admin_username"] = current_app.config[
        "CIVICFLOW_SETTINGS"
    ].admin_username
    csrf_token()
    session.permanent = True
    return {"authenticated": True, "csrf_token": session["csrf_token"]}


@admin_api.post("/logout")
@_api_login_required
def api_logout():
    if not valid_csrf_token(request.headers.get("X-CSRF-Token")):
        return _api_error("CSRF_VALIDATION_FAILED", "A valid CSRF token is required.", 400)
    session.clear()
    return {"authenticated": False}


@admin_api.get("/complaints")
@_api_login_required
def api_list_complaints():
    search = request.args.get("search", "").strip()
    category = request.args.get("category", "").strip()
    status = request.args.get("status", "").strip()
    if len(search) > 80:
        return _api_error("INVALID_SEARCH", "Search text must be 80 characters or fewer.", 400)
    if category and category not in COMPLAINT_CATEGORIES:
        return _api_error("INVALID_CATEGORY", "Choose a valid complaint category.", 400)
    if status and status not in COMPLAINT_STATUSES:
        return _api_error("INVALID_STATUS", "Choose a valid complaint status.", 400)
    try:
        return {"complaints": _repository().list_all(
            search=search, category=category, status=status
        )}
    except sqlite3.Error:
        current_app.logger.exception("Administrator complaint listing failed.")
        return _api_error("COMPLAINT_STORAGE_ERROR", "Complaint information is unavailable.", 503)


@admin_api.get("/complaints/<complaint_id>")
@_api_login_required
def api_get_complaint(complaint_id: str):
    try:
        complaint = _repository().get(complaint_id)
        history = _repository().history(complaint_id)
    except sqlite3.Error:
        current_app.logger.exception("Administrator complaint retrieval failed.")
        return _api_error("COMPLAINT_STORAGE_ERROR", "Complaint information is unavailable.", 503)
    if complaint is None or history is None:
        return _api_error("COMPLAINT_NOT_FOUND", "The complaint was not found.", 404)
    return {**complaint, "history": history}


@admin_api.patch("/complaints/<complaint_id>/status")
@_api_login_required
def api_update_complaint_status(complaint_id: str):
    if not valid_csrf_token(request.headers.get("X-CSRF-Token")):
        return _api_error("CSRF_VALIDATION_FAILED", "A valid CSRF token is required.", 400)
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return _api_error("INVALID_REQUEST", "Send a JSON object.", 400)
    new_status = payload.get("status")
    remarks = payload.get("remarks", "")
    if new_status not in COMPLAINT_STATUSES:
        return _api_error("INVALID_STATUS", "Choose a valid complaint status.", 400)
    if not isinstance(remarks, str) or len(remarks) > 2000:
        return _api_error("INVALID_REMARKS", "Remarks must be 2000 characters or fewer.", 400)
    try:
        complaint = _repository().update_status(
            complaint_id=complaint_id,
            new_status=new_status,
            remarks=remarks.strip(),
            updated_by=str(session.get("admin_username", "admin")),
        )
    except sqlite3.Error:
        current_app.logger.exception("Administrator complaint update failed.")
        return _api_error("COMPLAINT_STORAGE_ERROR", "The complaint could not be updated.", 503)
    if complaint is None:
        return _api_error("COMPLAINT_NOT_FOUND", "The complaint was not found.", 404)
    return complaint
