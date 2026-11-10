"""Smoke-test the REAL Gnani Prisma STT API with one audio clip (30 s or less).

Run from the project root, for example:
    python scripts\\test_prisma.py samples\\english1.m4a --language en-IN
    python scripts\\test_prisma.py samples\\english1.m4a --model prisma-v3.0 --language ta-IN,en-IN --format codemix

Every real response is saved as JSON under storage/stt_tests/ so you can inspect it.
The bundled Tamil and Tanglish clips are MP4; convert them to a supported audio-only format before testing.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.config import load_settings  # noqa: E402
from app.integrations.gnani_stt import GnaniSTTClient, GnaniSTTError  # noqa: E402


def main() -> int:
    # Tamil text needs UTF-8; legacy Windows consoles default to something else.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    settings = load_settings()
    parser = argparse.ArgumentParser(description="Test Gnani Prisma STT with one clip.")
    parser.add_argument("audio", help="Path to a clip of 30 s or less (wav/mp3/ogg/flac/aac/m4a)")
    parser.add_argument("--language", default=settings.stt_language, help="e.g. ta-IN, en-IN, or ta-IN,en-IN (v3.0 only)")
    parser.add_argument("--model", default=settings.stt_model, help="omit for Prisma v2.5; prisma-v3.0 for v3.0")
    parser.add_argument("--format", dest="fmt", default=settings.stt_format, help="verbatim | transcribe | codemix | transliterate")
    args = parser.parse_args()

    try:
        client = GnaniSTTClient(settings.gnani_api_key)
        result = client.transcribe(
            args.audio, language_code=args.language, model=args.model, fmt=args.fmt
        )
    except (GnaniSTTError, ValueError) as exc:
        print(f"FAILED: {exc}")
        return 1

    print(f"Model returned     : {result.model}")
    print(f"Language sent      : {args.language}")
    print(f"Detected language  : {result.detected_language_code or '(not returned)'}")
    print(f"Processing time    : {result.processing_time} s")
    print(f"End-to-end latency : {result.end_to_end_latency} s")
    print(f"Fields in response : {sorted(result.raw.keys())}")
    if result.truncated:
        print("WARNING: transcript was truncated by the API; use a shorter clip.")
    print("\nTranscript:")
    print(result.transcript if not result.is_empty else "(empty transcript: no speech detected)")

    out_dir = ROOT / "storage" / "stt_tests"
    out_dir.mkdir(parents=True, exist_ok=True)
    label = (args.model or "default-v2.5").replace("/", "-")
    out_file = out_dir / f"{Path(args.audio).stem}__{label}__{args.language.replace(',', '+')}__{args.fmt or 'default'}.json"
    payload = {
        "request": {"audio": Path(args.audio).name, "language_code": args.language, "model": args.model, "format": args.fmt},
        "response": result.raw,
    }
    out_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nSaved raw response to {out_file.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
