"""Gnani Prisma speech-to-text client (REST endpoint).

Endpoint : POST https://api.vachana.ai/stt/v3   (multipart/form-data)
Auth     : X-API-Key-ID header
Limits   : one clip of at most 30 s; WAV, MP3, OGG, FLAC, AAC or M4A
Model    : omit `model` for Prisma v2.5 (default); send "prisma-v3.0" for v3.0
Language : Prisma v2.5 takes ONE language code (e.g. ta-IN). Prisma v3.0 also
           takes indic-auto or a comma-separated list such as "ta-IN,en-IN".

The documented response contains no confidence score, so none is exposed here.
"""
from __future__ import annotations

import io
import mimetypes
import threading
import time
import wave
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional, Union

import requests

STT_URL = "https://api.vachana.ai/stt/v3"
MAX_CLIP_SECONDS = 30
SUPPORTED_EXTENSIONS = {".wav", ".mp3", ".ogg", ".flac", ".aac", ".m4a"}
RETRYABLE_STATUS = {429, 503, 504}


class GnaniSTTError(Exception):
    """Raised for any failure calling the Gnani STT API."""

    def __init__(
        self,
        message: str,
        *,
        status_code: Optional[int] = None,
        error_type: Optional[str] = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.error_type = error_type


@dataclass
class TranscriptResult:
    transcript: str
    model: Optional[str] = None
    detected_language_code: Optional[str] = None  # returned by Prisma v3.0 only
    request_id: Optional[str] = None
    processing_time: Optional[float] = None
    end_to_end_latency: Optional[float] = None
    truncated: bool = False
    raw: dict[str, Any] = field(default_factory=dict)  # untouched API response

    @property
    def is_empty(self) -> bool:
        return not self.transcript.strip()


def _check_wav_duration(data: bytes) -> None:
    """Reject WAV clips over the 30 s limit before spending credits on them."""
    try:
        with wave.open(io.BytesIO(data), "rb") as w:
            seconds = w.getnframes() / float(w.getframerate())
    except (wave.Error, EOFError, ZeroDivisionError):
        return  # not a plain PCM WAV; let the API judge it
    if seconds > MAX_CLIP_SECONDS:
        raise GnaniSTTError(
            f"Audio is {seconds:.1f}s; the REST endpoint accepts at most {MAX_CLIP_SECONDS}s.",
            error_type="MAX_AUDIO_DURATION_EXCEEDED",
        )


def _load_audio(audio: Union[str, Path, bytes], filename: Optional[str]) -> tuple[bytes, str]:
    if isinstance(audio, (str, Path)):
        path = Path(audio)
        if not path.is_file():
            raise GnaniSTTError(f"Audio file not found: {path}", error_type="FILE_NOT_FOUND")
        data, name = path.read_bytes(), filename or path.name
    else:
        data, name = bytes(audio), filename or "audio.wav"

    if not data:
        raise GnaniSTTError("Audio is empty.", error_type="EMPTY_AUDIO")
    ext = Path(name).suffix.lower()
    if ext not in SUPPORTED_EXTENSIONS:
        raise GnaniSTTError(
            f"Unsupported audio extension '{ext}'. Supported: {', '.join(sorted(SUPPORTED_EXTENSIONS))}",
            error_type="UNSUPPORTED_AUDIO_FORMAT",
        )
    if ext == ".wav":
        _check_wav_duration(data)
    return data, name


def _extract_error(response: Any) -> tuple[str, str]:
    """Return (error_type, message) from any of the error shapes the docs describe."""
    try:
        body = response.json()
    except ValueError:
        return "NON_JSON_RESPONSE", str(response.text)[:300]
    if not isinstance(body, dict):
        return "UNKNOWN_ERROR", str(body)[:300]

    err = body.get("error")
    if isinstance(err, dict):  # standard envelope: {"success": false, "error": {...}}
        return str(err.get("type", "UNKNOWN_ERROR")), str(err.get("message", ""))
    detail = body.get("detail")
    if isinstance(detail, dict):  # auth / rate-limit: {"detail": {"error_code": ...}}
        return str(detail.get("error_code", "UNKNOWN_ERROR")), str(detail.get("message", ""))
    if isinstance(detail, list):  # 422 validation: {"detail": [ {loc, msg}, ... ]}
        parts = [
            f"{'.'.join(map(str, d.get('loc', [])))}: {d.get('msg', '')}"
            for d in detail
            if isinstance(d, dict)
        ]
        return "VALIDATION_ERROR", "; ".join(parts)
    if "code" in body:  # 504 shape: {"error": "Gateway Timeout", "code": ..., "message": ...}
        return str(body["code"]), str(body.get("message", ""))
    return "UNKNOWN_ERROR", str(body)[:300]


class GnaniSTTClient:
    # The account may be limited to one active request at a time, so every
    # call in this process is serialised through one shared lock.
    _lock = threading.Lock()

    def __init__(
        self,
        api_key: str,
        *,
        url: str = STT_URL,
        timeout: float = 60.0,
        max_retries: int = 3,
        retry_delay: float = 1.0,
        session: Any = None,
    ) -> None:
        if not api_key:
            raise ValueError("GNANI_API_KEY is missing. Put it in .env (see .env.example).")
        self._api_key = api_key
        self._url = url
        self._timeout = timeout
        self._max_retries = max(1, max_retries)
        self._retry_delay = retry_delay
        self._session = session or requests.Session()

    def transcribe(
        self,
        audio: Union[str, Path, bytes],
        *,
        language_code: str = "ta-IN",
        model: Optional[str] = None,
        fmt: Optional[str] = None,
        filename: Optional[str] = None,
        request_id: Optional[str] = None,
    ) -> TranscriptResult:
        data, name = _load_audio(audio, filename)

        form: dict[str, str] = {"language_code": language_code}
        if model:
            form["model"] = model
        if fmt:
            form["format"] = fmt

        headers = {"X-API-Key-ID": self._api_key}
        if request_id:
            headers["X-API-Request-ID"] = request_id
        mime = mimetypes.guess_type(name)[0] or "application/octet-stream"

        with self._lock:
            response = self._post_with_retry(headers, form, name, data, mime)
        return self._parse(response)

    def _post_with_retry(self, headers, form, name, data, mime):
        for attempt in range(1, self._max_retries + 1):
            try:
                resp = self._session.post(
                    self._url,
                    headers=headers,
                    data=form,
                    files={"audio_file": (name, data, mime)},
                    timeout=self._timeout,
                )
            except requests.RequestException as exc:
                if attempt == self._max_retries:
                    raise GnaniSTTError(
                        f"Network error calling Gnani STT: {exc}", error_type="NETWORK_ERROR"
                    ) from exc
                time.sleep(self._retry_delay * attempt)
                continue
            if resp.status_code in RETRYABLE_STATUS and attempt < self._max_retries:
                time.sleep(self._retry_delay * attempt)
                continue
            return resp
        raise GnaniSTTError("Gnani STT request failed.", error_type="UNKNOWN_ERROR")

    @staticmethod
    def _parse(resp: Any) -> TranscriptResult:
        if resp.status_code != 200:
            etype, msg = _extract_error(resp)
            raise GnaniSTTError(
                f"Gnani STT error {resp.status_code} ({etype}): {msg}",
                status_code=resp.status_code,
                error_type=etype,
            )
        try:
            body = resp.json()
        except ValueError as exc:
            raise GnaniSTTError("Gnani STT returned a non-JSON 200 response.", error_type="NON_JSON_RESPONSE") from exc
        if not isinstance(body, dict) or body.get("success") is not True:
            raise GnaniSTTError(f"Unexpected Gnani STT response: {str(body)[:300]}", error_type="UNEXPECTED_RESPONSE")

        return TranscriptResult(
            transcript=str(body.get("transcript", "")),
            model=body.get("model"),
            detected_language_code=body.get("detected_language_code"),
            request_id=body.get("request_id"),
            processing_time=body.get("processing_time"),
            end_to_end_latency=body.get("end_to_end_latency"),
            truncated=bool(body.get("truncated", False)),
            raw=body,
        )
