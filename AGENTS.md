# AI Agent Guidelines for railcar-sim

This document helps AI coding agents understand conventions and patterns used in the railcar-sim project.

## Python Naming Conventions

### Underscore prefix on functions

Use leading underscores only for private helper functions that are **internal to a single module** and not intended to be called from outside it (e.g. `_run_build_algorithm` in `routers/dispatcher.py`).

Do **not** use leading underscores on functions in shared modules (`converters.py`, `schemas.py`) — these are public exports and should have clean names.

**Correct:**
```python
# In routers/dispatcher.py — private to this file
def _run_build_algorithm(origin_id, area_id, db): ...

# In converters.py — public export used by multiple routers
def dispatch_plan_to_dict(plan, db): ...
```

**Incorrect:**
```python
# In converters.py — this is a public shared helper, drop the underscore
def _dispatch_plan_to_dict(plan, db): ...  # ❌
```

Do **not** use leading underscores on module-level variables or constants.

**Correct:**
```python
prompts_dir = Path("prompts")
media_types = {...}
```

**Incorrect:**
```python
_prompts_dir = Path("prompts")  # ❌
_media_types = {...}  # ❌
```

---

## Project Structure

- **main.py** — FastAPI app entry point; registers routers, mounts static files, handles startup
- **schemas.py** — All Pydantic request/response models
- **converters.py** — Shared model-to-dict helpers and settings/clock utilities
- **routers/** — API route handlers, one file per domain (cars, waybills, locations, industries, commodity_map, car_types, dispatcher, session, automation, uploads, settings, operations, export_import)
- **models.py** — SQLAlchemy ORM models
- **database.py** — Database initialization and session management (SQLite)
- **vision.py** — Vision provider abstractions (Anthropic, OpenAI, Ollama, Gemini)
- **templates/** — Jinja2 HTML templates for the web UI
- **static/** — Frontend JavaScript and CSS
- **prompts/** — JSON config files for vision model prompts
- **uploads/** — Uploaded car photos (auto-created)

---

## Key Technologies

- **Framework:** FastAPI + Uvicorn
- **Database:** SQLite with SQLAlchemy ORM
- **Frontend:** Vanilla JavaScript + HTML/CSS
- **Vision APIs:** Anthropic Claude, OpenAI GPT-4o, Google Gemini, or local Ollama
- **Image Processing:** Pillow (PIL)

---

## Running the App

See [README.md](README.md) for setup instructions. Quick start:

```bash
source .venv/bin/activate
.venv/bin/python3 -m uvicorn main:app --reload
# Open http://localhost:8000
```

---

## Git Workflow

- **Always create a new branch before starting any new feature or significant change.** Never implement directly on `main`.
- Branch naming: use a short kebab-case description, e.g. `feature/per-car-auto-assign`, `fix/hopper-matching`.
- After the user approves a plan, create the branch first, then implement.
- When work is complete and the user confirms, merge the branch into `main`.

---

## Development Notes

- The app runs on SQLite — no external database setup needed
- Vision analysis is optional; the app works without an API key configured
- Use `--reload` during development for hot-reload on file changes
- Environment variables are loaded from `.env` using python-dotenv
