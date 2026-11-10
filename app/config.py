"""Central configuration, read from environment variables / .env (never hard-code keys)."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parent.parent
load_dotenv(ROOT_DIR / ".env")


@dataclass(frozen=True)
class Settings:
    gnani_api_key: str
    stt_model: Optional[str]    # None -> API default (Prisma v2.5)
    stt_language: str           # e.g. "ta-IN"
    stt_format: Optional[str]   # None -> API default
    max_audio_bytes: int = 10_000_000


def load_settings() -> Settings:
    return Settings(
        gnani_api_key=os.getenv("GNANI_API_KEY", "").strip(),
        stt_model=os.getenv("GNANI_STT_MODEL", "prisma-v3.0").strip() or None,
        stt_language=os.getenv("GNANI_STT_LANGUAGE", "ta-IN,en-IN").strip() or "ta-IN,en-IN",
        stt_format=os.getenv("GNANI_STT_FORMAT", "codemix").strip() or None,
    )
