# zerotodemo
This repository is for the Zero To Demo hackathon in San Francisco.

## Calendar handler backend (`backend/`)

A FastAPI service that implements [CONTRACT.md](CONTRACT.md): `GET /health`, `GET /events`, `POST /chat`, `POST /apply`.

### Run locally
```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env          # MOCK=1 by default
uvicorn app.main:app --reload --port 8000
```
Open http://localhost:8000/docs for the interactive API docs.

```bash
cd backend && pytest -q
```

Python 3.10 or newer is required (`python3 --version`). The macOS system Python is 3.9: install a newer one with `brew install python@3.12` and create the venv with `python3.12 -m venv .venv`.

### Modes
| Variable | Values | Default |
|---|---|---|
| `CALENDAR` | `mock` (in-memory) or `google` (the demo account) | follows `MOCK` |
| `AGENT` | `mock` (keyword bot) or `real` (Tom's agent in `app/agent.py`) | follows `MOCK` |
| `MOCK` | `1` = both mock, `0` = both real | `1` |

### Google Calendar (demo account)
One-time setup in Google Cloud Console:
1. Create a project, then enable **Google Calendar API**.
2. Set up the **OAuth consent screen**: type External, and add the demo Gmail under *Test users*.
3. Go to **Credentials → Create OAuth client ID → Desktop app**, download the JSON and save it as `backend/client_secret.json`.

From `backend/`, with the venv active:
```bash
python scripts/google_auth.py      # opens the browser; sign in with the demo Gmail and writes token.json
python scripts/seed.py             # fills the calendar with the demo fortnight
python scripts/seed.py --reset     # wipe what the demo created and seed again
CALENDAR=google AGENT=mock uvicorn app.main:app --port 8000
```
For Render, set `CALENDAR=google` and paste the contents of `token.json` into `GOOGLE_TOKEN_JSON`.
In Google's *Testing* mode the sign-in expires after 7 days; run `google_auth.py` again if that happens.
Never commit `client_secret.json` or `token.json`.

### Mock mode (`MOCK=1`)
Every endpoint returns realistic data in the exact contract shape:
- A two-week busy calendar (standups, a 1:1 with Tom, an investor call and more) that tracks the current date. On a weekend it starts from the coming Monday.
- A keyword-based mock agent for `/chat`. Try "move my 1:1 with Tom to tomorrow afternoon", "cancel the dentist", "schedule a 1 hour meeting with Anna" or "when am I free?".
- `/apply` changes the in-memory calendar, so `/events` reflects the change. Restarting the server resets it.

### Layout
```
backend/app/
  main.py           routes, CORS
  models.py         Pydantic models that mirror CONTRACT.md one to one
  errors.py         contract error format and exception handlers
  calendar/         CalendarBackend interface; mock.py (MOCK=1), google.py (task 2)
  free_slots.py     deterministic free-slot finder
  tools.py          agent tool implementations, plus apply_change
  sessions.py       in-memory sessions (chat history, proposed changes)
  agent_adapter.py  bridge to Tom's agent (AgentCalendar), plus the mock agent
backend/agent/      Tom's agent: agent.py (Claude loop, prompt, tools), cli.py, fake_calendar.py
```
`CONTRACT.md` describes both the API that the UI uses (Part 1) and the agent ↔ backend interface (Part 2).

### Deploy (Render)
1. In Render, go to **New → Blueprint** and pick this repo. `render.yaml` sets up the service with `MOCK=1`.
2. The CORS settings already allow `*.lovable.app`, `*.lovable.dev` and `*.lovableproject.com`. Add other origins with `CORS_ORIGINS`.
