"""CivicFlow Flask application factory."""

from __future__ import annotations

import secrets
from datetime import timedelta
from typing import Optional

from flask import Flask, render_template
from werkzeug.exceptions import BadRequest, RequestEntityTooLarge

from app.config import Settings, load_settings
from app.integrations.gnani_stt import GnaniSTTClient
from app.services.complaint_repository import ComplaintRepository
from app.services.request_assessor import LocalRequestAssessor
from app.services.request_workflow import RequestWorkflow
from app.api.admin_routes import admin_api, admin_pages
from app.api.complaint_routes import complaints_api
from app.api.routes import api


def create_app(
    settings: Optional[Settings] = None,
    *,
    stt_client: Optional[GnaniSTTClient] = None,
    assessor: Optional[LocalRequestAssessor] = None,
    complaint_repository: Optional[ComplaintRepository] = None,
) -> Flask:
    settings = settings or load_settings()
    app = Flask(__name__)
    app.secret_key = settings.secret_key or secrets.token_urlsafe(32)
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    app.config["SESSION_COOKIE_SECURE"] = settings.session_cookie_secure
    app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(hours=8)
    app.config["MAX_CONTENT_LENGTH"] = settings.max_audio_bytes
    app.config["CIVICFLOW_SETTINGS"] = settings

    if stt_client is None:
        if not settings.gnani_api_key:
            raise RuntimeError("GNANI_API_KEY is required to start CivicFlow.")
        stt_client = GnaniSTTClient(settings.gnani_api_key)
    if assessor is None:
        assessor = LocalRequestAssessor()

    app.extensions["civicflow_stt"] = stt_client
    app.extensions["civicflow_workflow"] = RequestWorkflow(assessor)
    app.extensions["civicflow_complaints"] = (
        complaint_repository
        if complaint_repository is not None
        else ComplaintRepository(settings.database_path)
    )
    app.register_blueprint(api, url_prefix="/api/v1")
    app.register_blueprint(complaints_api, url_prefix="/api/v1")
    app.register_blueprint(admin_api, url_prefix="/api/v1/admin")
    app.register_blueprint(admin_pages, url_prefix="/admin")

    @app.get("/")
    def homepage():
        return render_template("index.html", max_audio_bytes=settings.max_audio_bytes)

    @app.get("/healthz")
    def healthcheck():
        return {"status": "ok"}

    @app.get("/complaints")
    def citizen_dashboard():
        return render_template("citizen_dashboard.html")

    @app.errorhandler(RequestEntityTooLarge)
    def too_large(_error):
        return {"error": {"code": "UPLOAD_TOO_LARGE", "message": "Audio upload exceeds the size limit."}}, 413

    @app.errorhandler(BadRequest)
    def bad_request(_error):
        return {"error": {"code": "INVALID_REQUEST", "message": "The request body is invalid."}}, 400

    return app
