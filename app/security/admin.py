"""Environment-configured administrator authentication and CSRF helpers."""

from __future__ import annotations

import hmac
import secrets

from flask import current_app, session
from werkzeug.security import check_password_hash


def admin_auth_configured() -> bool:
    settings = current_app.config["CIVICFLOW_SETTINGS"]
    return bool(
        len(settings.secret_key) >= 32
        and settings.admin_username
        and settings.admin_password_hash
    )


def csrf_token() -> str:
    token = session.get("csrf_token")
    if not isinstance(token, str):
        token = secrets.token_urlsafe(32)
        session["csrf_token"] = token
    return token


def valid_csrf_token(candidate: object) -> bool:
    known_token = session.get("csrf_token")
    return (
        isinstance(candidate, str)
        and isinstance(known_token, str)
        and hmac.compare_digest(candidate, known_token)
    )


def authenticate_admin(username: object, password: object) -> bool:
    settings = current_app.config["CIVICFLOW_SETTINGS"]
    if (
        not isinstance(username, str)
        or not isinstance(password, str)
        or len(username) > 128
        or len(password) > 1024
    ):
        return False
    try:
        password_matches = check_password_hash(
            settings.admin_password_hash, password
        )
    except (ValueError, TypeError):
        current_app.logger.error("Administrator password hash configuration is invalid.")
        return False
    username_matches = hmac.compare_digest(username, settings.admin_username)
    return username_matches and password_matches
