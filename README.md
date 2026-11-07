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
  agent_adapter.py  seam for Tom's run_agent; mock agent
```

### Deploy (Render)
1. In Render, go to **New → Blueprint** and pick this repo. `render.yaml` sets up the service with `MOCK=1`.
2. The CORS settings already allow `*.lovable.app`, `*.lovable.dev` and `*.lovableproject.com`. Add other origins with `CORS_ORIGINS`.
