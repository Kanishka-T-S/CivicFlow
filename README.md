# CivicFlow

CivicFlow is a voice-first prototype for preparing civic-service requests. It is
intended to make it easier for a resident to describe a local issue, review a
transcription, add a location, and confirm a complaint.

Confirmed complaints are stored locally in SQLite and can be tracked by the
citizen and managed by an authenticated administrator. CivicFlow does not send
complaints to a government office. It uses Gnani Prisma for speech-to-text and
deterministic local keyword rules for request classification; it does not use
Claude or another GenAI reasoning service.

## Features

- Flask homepage for uploading an audio recording.
- Gnani Prisma speech-to-text integration, configured by environment variables.
- English/Tamil language configuration and bilingual `ta-IN,en-IN` with `codemix` when
  supported by the configured Prisma model/account.
- Local keyword classification for roads, water, sanitation, waste, and utilities.
- Multi-step request intake that asks the resident to provide a location.
- Request review and citizen confirmation; only confirmed complaints are saved.
- SQLite persistence, unique complaint IDs, and append-only status history.
- Private citizen tracking codes; only code holders can list and view their complaints.
- Administrator login, complaint search/filtering, status changes, and remarks.
- Unit and Flask API tests that use a fake STT client.

## Architecture and request flow

1. A resident selects an M4A, MP3, or WAV file on the homepage.
2. The browser sends the audio as multipart form data to
   `POST /api/v1/requests`.
3. Flask checks the file extension and size, then calls the Gnani STT client.
4. The transcript is classified with local keyword matching. The workflow retains
   the transcript as the description and asks for a location.
5. The resident can send a follow-up message to add the location, review the
   transcript and request details, and confirm the complaint.
6. Confirmation transactionally creates one SQLite complaint, a unique complaint
   ID, an initial `Pending` status-history record, and a private tracking code.
   Repeated confirmation of the same active workflow does not create duplicates.
7. Citizen tracking requests require the tracking code. Its SHA-256 hash, rather
   than the code itself, is stored in the database. The browser keeps the code in
   local storage so the citizen can list complaints tied to that code.
8. Request-intake state remains process-local and expires after 30 minutes;
   submitted complaints and their updates persist in SQLite across restarts.
9. Administrators sign in with credentials configured in the environment. Status
   changes and remarks are appended to complaint history and never replace older
   entries.

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
|   |-- api/complaint_routes.py       # Private citizen complaint tracking API
|   |-- api/admin_routes.py           # Administrator pages and authenticated API
|   |-- integrations/gnani_stt.py     # Gnani Prisma STT client
|   |-- security/admin.py             # Admin password and CSRF helpers
|   |-- services/complaint_repository.py # SQLite schema and repository
|   |-- services/request_assessor.py  # Local keyword classification and intake
|   |-- services/request_workflow.py  # In-memory request lifecycle
|   |-- static/                       # Homepage and dashboard CSS/JavaScript
|   |-- templates/                   # Citizen and administrator pages
|   |-- config.py                     # Environment-based configuration
|   `-- __init__.py                   # Flask application factory and web routes
|-- samples/                          # Local audio only; sample recordings are ignored by Git
|-- scripts/test_prisma.py            # Optional real Gnani API smoke test
|-- tests/                            # Unit, API, persistence, and admin tests
|-- storage/                          # SQLite database; generated and Git-ignored
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

The database is created at `storage/civicflow.sqlite3` by default. Override it
with `CIVICFLOW_DATABASE_PATH` if required. The directory is created automatically
and is ignored by Git.

### Configure administrator access

Administrator access is disabled until all three variables below are set in the
local `.env` file:

- `CIVICFLOW_SECRET_KEY`: a long random key used to sign administrator sessions.
- `CIVICFLOW_ADMIN_USERNAME`: the administrator login name.
- `CIVICFLOW_ADMIN_PASSWORD_HASH`: a Werkzeug password hash, not a plaintext password.

Generate a session key and a password hash locally with PowerShell:

```powershell
python -c "import secrets; print(secrets.token_urlsafe(32))"
python -c "import getpass; from werkzeug.security import generate_password_hash; print(generate_password_hash(getpass.getpass()))"
```

Copy the outputs into `.env`; the second command prompts for the password without
echoing it. Never commit `.env` or place a plaintext administrator password in
configuration. `CIVICFLOW_COOKIE_SECURE=true` should be used when the application
is served over HTTPS; keep it `false` for local HTTP development.

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
| `POST` | `/api/v1/requests/<request_id>/confirm` | Register a complete confirmed complaint in SQLite; optionally include a known `tracking_code` |
| `GET` | `/complaints` | Citizen dashboard; tracking code is required to load complaint data |
| `GET` | `/api/v1/complaints` | List complaints associated with the `Authorization: Bearer <tracking_code>` credential |
| `GET` | `/api/v1/complaints/<complaint_id>` | View complaint details and history with the tracking code |
| `GET` | `/api/v1/complaints/<complaint_id>/status` | View the authorized complaint status |
| `GET` | `/api/v1/complaints/<complaint_id>/history` | View authorized complaint status history |
| `GET` | `/admin/login` | Administrator sign-in page |
| `GET` | `/admin` | Search/filter and view all complaints after administrator sign-in |
| `GET` | `/admin/complaints/<complaint_id>` | Administrator complaint detail and update form |
| `POST` | `/admin/complaints/<complaint_id>/status` | Change status and append administrative remarks; CSRF token required |
| `POST` | `/admin/logout` | End administrator session; CSRF token required |
| `GET` | `/api/v1/admin/csrf` | Obtain a session CSRF token for administrator API operations |
| `POST` | `/api/v1/admin/login` | Authenticate administrator with JSON credentials and CSRF header |
| `GET` | `/api/v1/admin/complaints` | Authenticated/filterable administrator complaint listing |
| `GET` | `/api/v1/admin/complaints/<complaint_id>` | Authenticated complaint detail and history |
| `PATCH` | `/api/v1/admin/complaints/<complaint_id>/status` | Authenticated status/remarks update; CSRF header required |
| `POST` | `/api/v1/admin/logout` | End administrator API session; CSRF header required |

Citizen APIs require the private tracking code in the `Authorization` header.
Administrator APIs require a signed login session and CSRF token for state
changes. Supported complaint categories are Road Damage, Water Supply, Garbage
Collection, Street Light, Drainage, Electricity, Public Sanitation, and Other.
Statuses are Pending, In Progress, Resolved, and Rejected.

### Database structure

The standard-library SQLite database uses two tables:

- `complaints`: internal ID, unique public complaint ID, unique source workflow
  ID, hashed citizen tracking code, category, description, location, submission
  timestamp, current status, and last-updated timestamp.
- `complaint_updates`: complaint reference, previous/new status, timestamp,
  administrative remarks, and actor. The initial submission is also recorded.

Initialization uses non-destructive `CREATE TABLE IF NOT EXISTS` statements,
foreign keys, check constraints, indexes, and SQLite `user_version`. Status
updates and their history records are committed in one transaction. No citizen
account or unnecessary personal contact information is stored.

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
- Confirmed complaints persist in the local SQLite database. Private tracking
  codes are returned to the browser and stored in local storage; anyone who
  obtains a code can access the complaints associated with it. Losing the code
  has no recovery path in this prototype.
- The optional smoke-test script saves raw provider responses locally in the
  ignored `storage` directory.
- The homepage stylesheet currently imports fonts from Google Fonts, which causes
  the browser to contact that service when loading the page.
- Citizens use anonymous bearer tracking codes rather than accounts. Admin
  authentication is environment-configured, but deployment still requires a
  strong session key, HTTPS, secure cookie configuration, backups, access
  controls, and an operational security review.
- Complaints are not transmitted to a government portal. The local database is
  not replicated or backed up automatically.

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
- The in-memory intake workflow is process-local, is lost on restart, and is
  unsuitable for multiple independent workers. Confirmed records are durable.
- Upload checks rely on filename extension and request size; the browser's
  10 MB/format checks are not a security boundary.
- Future work should improve classification and multi-turn field collection, add
  durable shared storage and operational safeguards, and define a production
  deployment and retention policy before public use.
