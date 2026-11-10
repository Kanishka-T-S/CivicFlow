"""CivicFlow Flask application factory."""

from __future__ import annotations

from typing import Optional

from flask import Flask, render_template
from werkzeug.exceptions import BadRequest, RequestEntityTooLarge

from app.config import Settings, load_settings
from app.integrations.gnani_stt import GnaniSTTClient
from app.services.request_assessor import LocalRequestAssessor
from app.services.request_workflow import RequestWorkflow
from app.api.routes import api


def create_app(
    settings: Optional[Settings] = None,
    *,
    stt_client: Optional[GnaniSTTClient] = None,
    assessor: Optional[LocalRequestAssessor] = None,
) -> Flask:
    settings = settings or load_settings()
    app = Flask(__name__)
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
    app.register_blueprint(api, url_prefix="/api/v1")

    @app.get("/")
    def homepage():
        return render_template("index.html", max_audio_bytes=settings.max_audio_bytes)

    @app.get("/healthz")
    def healthcheck():
        return {"status": "ok"}

    @app.errorhandler(RequestEntityTooLarge)
    def too_large(_error):
        return {"error": {"code": "UPLOAD_TOO_LARGE", "message": "Audio upload exceeds the size limit."}}, 413

    @app.errorhandler(BadRequest)
    def bad_request(_error):
        return {"error": {"code": "INVALID_REQUEST", "message": "The request body is invalid."}}, 400

    return app
