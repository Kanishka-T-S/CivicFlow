"""Central configuration, read from environment variables / .env (never hard-code keys)."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parent.parent
DEFAULT_DATABASE_PATH = ROOT_DIR / "storage" / "civicflow.sqlite3"
load_dotenv(ROOT_DIR / ".env")


@dataclass(frozen=True)
class Settings:
    gnani_api_key: str
    stt_model: Optional[str]    # None -> API default (Prisma v2.5)
    stt_language: str           # e.g. "ta-IN"
    stt_format: Optional[str]   # None -> API default
    max_audio_bytes: int = 10_000_000
    database_path: str = str(DEFAULT_DATABASE_PATH)
    secret_key: str = ""
    admin_username: str = ""
    admin_password_hash: str = ""
    session_cookie_secure: bool = False


def load_settings() -> Settings:
    database_path = os.getenv("CIVICFLOW_DATABASE_PATH", "").strip()
    if not database_path:
        database_path = str(DEFAULT_DATABASE_PATH)
    elif database_path != ":memory:":
        configured_path = Path(database_path).expanduser()
        if not configured_path.is_absolute():
            configured_path = ROOT_DIR / configured_path
        database_path = str(configured_path)

    return Settings(
        gnani_api_key=os.getenv("GNANI_API_KEY", "").strip(),
        stt_model=os.getenv("GNANI_STT_MODEL", "prisma-v3.0").strip() or None,
        stt_language=os.getenv("GNANI_STT_LANGUAGE", "ta-IN,en-IN").strip() or "ta-IN,en-IN",
        stt_format=os.getenv("GNANI_STT_FORMAT", "codemix").strip() or None,
        database_path=database_path,
        secret_key=os.getenv("CIVICFLOW_SECRET_KEY", "").strip(),
        admin_username=os.getenv("CIVICFLOW_ADMIN_USERNAME", "").strip(),
        admin_password_hash=os.getenv("CIVICFLOW_ADMIN_PASSWORD_HASH", "").strip(),
        session_cookie_secure=os.getenv("CIVICFLOW_COOKIE_SECURE", "").strip().lower()
        in {"1", "true", "yes", "on"},
    )
