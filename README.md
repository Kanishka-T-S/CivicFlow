# CivicFlow

CivicFlow is a voice-first prototype for preparing civic-service requests. It is
intended to make it easier for a resident to describe a local issue, review a
transcription, add a location, and confirm a draft request.

The current application does not send complaints to a government office. It uses
Gnani Prisma for speech-to-text and deterministic local keyword rules for request
classification; it does not use Claude or another GenAI reasoning service.

## Features

- Flask homepage for uploading an audio recording.
- Gnani Prisma speech-to-text integration, configured by environment variables.
- English/Tamil language configuration and bilingual `ta-IN,en-IN` with `codemix` when
  supported by the configured Prisma model/account.
- Local keyword classification for roads, water, sanitation, waste, and utilities.
- Multi-step request intake that asks the resident to provide a location.
- Request review and local confirmation. Confirmation does not submit the request.
- Unit and Flask API tests that use a fake STT client.

## Architecture and request flow

1. A resident selects an M4A, MP3, or WAV file on the homepage.
2. The browser sends the audio as multipart form data to
   `POST /api/v1/requests`.
3. Flask checks the file extension and size, then calls the Gnani STT client.
4. The transcript is classified with local keyword matching. The workflow retains
   the transcript as the description and asks for a location.
5. The resident can send a follow-up message to add the location, review the
   transcript and request details, and confirm the draft.
6. Request state is kept in process memory and expires after 30 minutes of
   inactivity. Restarting the process loses active requests.

## Technology

- Python 3.12 (the version used for project verification; no formal version range
  is declared)
- Flask
- Requests
- python-dotenv
- Gnani Prisma STT REST API
- HTML, CSS, and browser JavaScript
- `unittest`-style tests, also discoverable with pytest

## Project structure

```text
civicflow/
|-- app/
|   |-- api/routes.py                 # Flask request, follow-up, and confirmation API
|   |-- integrations/gnani_stt.py     # Gnani Prisma STT client
|   |-- services/request_assessor.py  # Local keyword classification and intake
|   |-- services/request_workflow.py  # In-memory request lifecycle
|   |-- static/                       # Homepage CSS and JavaScript
|   |-- templates/index.html          # CivicFlow homepage
|   |-- config.py                     # Environment-based configuration
|   `-- __init__.py                   # Flask application factory and web routes
|-- samples/                          # Local audio only; sample recordings are ignored by Git
|-- scripts/test_prisma.py            # Optional real Gnani API smoke test
|-- tests/                            # Mocked unit and API tests
|-- .env.example                      # Placeholder configuration template
|-- .gitignore
|-- requirements.txt
`-- run.py                            # Local development entry point
```

## Windows PowerShell setup

Run commands from the project directory:

```powershell
py -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
notepad .env
```

If PowerShell prevents environment activation, allow it only for the current
PowerShell process:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.venv\Scripts\Activate.ps1
```

In `.env`, replace the `GNANI_API_KEY` placeholder with a valid key from Gnani. Do
not commit or share `.env`. The application requires this key to start. No
Anthropic/Claude credentials are used or required.

## Gnani STT configuration

The settings template defaults to:

```dotenv
GNANI_STT_MODEL=prisma-v3.0
GNANI_STT_LANGUAGE=ta-IN,en-IN
GNANI_STT_FORMAT=codemix
```

The Gnani client sends a multipart request to `https://api.vachana.ai/stt/v3`
using the `X-API-Key-ID` authentication header. Prisma model, language, and format
can be changed in `.env` to match account access and the desired language mode.
Prisma v2.5 uses one language code; the project has previously verified the
bilingual/codemix option with v3.0. Test actual transcription with your own audio
and account before relying on its accuracy.

The API client accepts WAV, MP3, OGG, FLAC, AAC, and M4A and documents a maximum
clip duration of 30 seconds. Local duration checking is implemented for WAV; other
formats rely on Gnani to enforce its limit. The homepage only offers M4A, MP3, and
WAV uploads and limits requests to 10 MB. MP4 is not a supported STT input format.

## Start the application

With the virtual environment active and `.env` configured:

```powershell
python run.py
```

Open <http://127.0.0.1:5000/>. This starts Flask's local development server; it is
not a production deployment configuration.

## HTTP endpoints

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/` | CivicFlow homepage |
| `GET` | `/healthz` | Liveness response |
| `POST` | `/api/v1/requests` | Upload an `audio` multipart field, transcribe, and start intake |
| `GET` | `/api/v1/requests/<request_id>` | Get a request still held by this process |
| `POST` | `/api/v1/requests/<request_id>/messages` | Send a JSON object such as `{"text":"Main Street"}` as a follow-up |
| `POST` | `/api/v1/requests/<request_id>/confirm` | Confirm a complete request locally |

Confirmation only updates the in-memory workflow status. It does not deliver,
register, or submit a complaint to any external authority.

## Test

Run the complete test suite using Python's standard library:

```powershell
python -m unittest discover -s tests -v
```

If pytest is installed in the environment, the same tests can also be run with:

```powershell
python -m pytest -q
```

The tests use fake STT responses and do not call the Gnani API. For an optional
live API check, create a local `samples` directory and put your own supported clip
there. The directory's audio files are Git-ignored:

```powershell
New-Item -ItemType Directory -Force samples
python scripts\test_prisma.py samples\my_clip.m4a --language en-IN
python scripts\test_prisma.py samples\my_clip.m4a --model prisma-v3.0 --language ta-IN,en-IN --format codemix
```

Live tests send audio to Gnani and may consume account quota. The smoke-test script
writes raw API responses under `storage\stt_tests\`; that directory is local and
Git-ignored. Do not use personal or sensitive recordings unless you have approval
and have reviewed the provider's data-handling terms.

## Privacy and data handling

- Audio uploaded through the application is sent to Gnani for transcription. The
  application does not save that uploaded audio to disk.
- Transcript, location, and request details are held in process memory until the
  request expires after 30 minutes of inactivity or the process restarts.
- The optional smoke-test script saves raw provider responses locally in the
  ignored `storage` directory.
- The homepage stylesheet currently imports fonts from Google Fonts, which causes
  the browser to contact that service when loading the page.
- There is no user authentication, database persistence, or government-portal
  integration. This prototype is not suitable for real citizen data without a
  privacy and security review.

## Known limitations and future improvements

- Classification is based on ordered keyword substring matching, not an AI model.
  It can miss issues, over-match words, or classify a request mentioning multiple
  services as only one category.
- The current workflow always asks for the location, even when it may appear in
  the initial transcript. Follow-up text is treated as the location; urgency is
  not collected despite being represented in the request data.
- Tamil classification covers only a small keyword set. Tanglish coverage,
  transcription quality across accents, and translated interface text need more
  testing.
- The in-memory store is process-local, is lost on restart, and is unsuitable for
  multiple independent workers.
- Upload checks rely on filename extension and request size; the browser's
  10 MB/format checks are not a security boundary.
- Future work should improve classification and multi-turn field collection, add
  durable shared storage and operational safeguards, and define a production
  deployment and retention policy before public use.
