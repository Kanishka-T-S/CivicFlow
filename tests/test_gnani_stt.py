"""Unit tests for the Gnani STT client.

IMPORTANT: these use a FAKE HTTP session whose payloads follow the documented
response schema. They verify our request building, parsing, retry and error
handling. They do NOT call Gnani and say nothing about real transcription accuracy.
"""
from __future__ import annotations

import io
import json
import sys
import unittest
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.integrations.gnani_stt import STT_URL, GnaniSTTClient, GnaniSTTError  # noqa: E402

DOC_SHAPED_OK = {
    "success": True,
    "request_id": "req_test",
    "transcript": "sample text",
    "model": "prisma-v2.5",
    "processing_time": 0.1,
    "end_to_end_latency": 0.2,
    "output": {"literal": "sample text"},
}


class FakeResponse:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload
        self.text = json.dumps(payload) if payload is not None else ""

    def json(self):
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.responses.pop(0)


def make_wav(seconds: float, rate: int = 8000) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x00\x00" * int(rate * seconds))
    return buf.getvalue()


def client_with(responses, **kw):
    session = FakeSession(responses)
    return GnaniSTTClient("test-key", session=session, retry_delay=0, **kw), session


class GnaniSTTClientTests(unittest.TestCase):
    def test_request_shape_default_model(self):
        client, session = client_with([FakeResponse(200, DOC_SHAPED_OK)])
        result = client.transcribe(make_wav(1), language_code="ta-IN", filename="clip.wav")
        url, kw = session.calls[0]
        self.assertEqual(url, STT_URL)
        self.assertEqual(kw["headers"]["X-API-Key-ID"], "test-key")
        self.assertEqual(kw["data"], {"language_code": "ta-IN"})  # no model => Prisma v2.5 default
        self.assertEqual(kw["files"]["audio_file"][0], "clip.wav")
        self.assertEqual(result.transcript, "sample text")
        self.assertEqual(result.model, "prisma-v2.5")

    def test_model_and_format_are_sent_when_set(self):
        client, session = client_with([FakeResponse(200, DOC_SHAPED_OK)])
        client.transcribe(make_wav(1), language_code="ta-IN,en-IN", model="prisma-v3.0", fmt="codemix")
        self.assertEqual(
            session.calls[0][1]["data"],
            {"language_code": "ta-IN,en-IN", "model": "prisma-v3.0", "format": "codemix"},
        )

    def test_no_confidence_is_exposed(self):
        client, _ = client_with([FakeResponse(200, DOC_SHAPED_OK)])
        result = client.transcribe(make_wav(1))
        self.assertFalse(hasattr(result, "confidence"))

    def test_auth_error_shape(self):
        payload = {"detail": {"error_code": "INVALID_API_KEY", "message": "Unauthorized", "status_code": 401}}
        client, _ = client_with([FakeResponse(401, payload)])
        with self.assertRaises(GnaniSTTError) as ctx:
            client.transcribe(make_wav(1))
        self.assertEqual(ctx.exception.error_type, "INVALID_API_KEY")
        self.assertEqual(ctx.exception.status_code, 401)

    def test_standard_envelope_error(self):
        payload = {"success": False, "error": {"type": "INVALID_LANGUAGE_CODE", "message": "bad code"}}
        client, _ = client_with([FakeResponse(400, payload)])
        with self.assertRaises(GnaniSTTError) as ctx:
            client.transcribe(make_wav(1), language_code="xx-XX")
        self.assertEqual(ctx.exception.error_type, "INVALID_LANGUAGE_CODE")

    def test_retries_on_429_then_succeeds(self):
        rate = {"detail": {"error_code": "RATE_LIMITED", "message": "wait", "status_code": 429}}
        client, session = client_with([FakeResponse(429, rate), FakeResponse(200, DOC_SHAPED_OK)])
        result = client.transcribe(make_wav(1))
        self.assertEqual(len(session.calls), 2)
        self.assertEqual(result.transcript, "sample text")

    def test_gives_up_after_max_retries(self):
        rate = {"detail": {"error_code": "RATE_LIMITED", "message": "wait", "status_code": 429}}
        client, session = client_with([FakeResponse(429, rate)] * 3, max_retries=3)
        with self.assertRaises(GnaniSTTError) as ctx:
            client.transcribe(make_wav(1))
        self.assertEqual(len(session.calls), 3)
        self.assertEqual(ctx.exception.error_type, "RATE_LIMITED")

    def test_wav_over_30s_rejected_without_http_call(self):
        client, session = client_with([])
        with self.assertRaises(GnaniSTTError) as ctx:
            client.transcribe(make_wav(31), filename="long.wav")
        self.assertEqual(ctx.exception.error_type, "MAX_AUDIO_DURATION_EXCEEDED")
        self.assertEqual(session.calls, [])

    def test_unsupported_extension_rejected(self):
        client, session = client_with([])
        with self.assertRaises(GnaniSTTError) as ctx:
            client.transcribe(b"1234", filename="clip.webm")
        self.assertEqual(ctx.exception.error_type, "UNSUPPORTED_AUDIO_FORMAT")
        self.assertEqual(session.calls, [])

    def test_missing_api_key(self):
        with self.assertRaises(ValueError):
            GnaniSTTClient("")

    def test_empty_transcript_is_not_an_error(self):
        client, _ = client_with([FakeResponse(200, {"success": True, "request_id": "r", "transcript": ""})])
        result = client.transcribe(make_wav(1))
        self.assertTrue(result.is_empty)


if __name__ == "__main__":
    unittest.main()
