# AI Agent Guidelines for railcar-sim

This document helps AI coding agents understand conventions and patterns used in the railcar-sim project.

## Python Naming Conventions

### No Leading Underscores
Do **not** use leading underscores (`_`) to prefix variable names, function names, or constants in Python. This project avoids Python's convention for name-mangling and private members.

**Correct:**
```python
prompts_dir = Path("prompts")
stylize_cfg = load_stylize_config()
media_types = {...}
```

**Incorrect:**
```python
_prompts_dir = Path("prompts")  # ❌ avoid
_stylize_cfg = load_stylize_config()  # ❌ avoid
_media_types = {...}  # ❌ avoid
```

This applies to:
- Module-level variables and constants
- Function definitions
- Helper functions (use descriptive names instead)

---

## Project Structure

- **main.py** — FastAPI application, routes, and request handlers
- **models.py** — SQLAlchemy ORM models (Car, Location, Industry, Waybill, MovementLog, CommodityCarTypeMap)
- **database.py** — Database initialization and session management (SQLite)
- **vision.py** — Vision provider abstractions (Anthropic, OpenAI, Ollama)
- **templates/** — Jinja2 HTML templates for the web UI
- **static/** — Frontend JavaScript and CSS
- **prompts/** — JSON config files for vision model prompts
- **uploads/** — Temporary directory for uploaded car photos

---

## Key Technologies

- **Framework:** FastAPI + Uvicorn
- **Database:** SQLite with SQLAlchemy ORM
- **Frontend:** Vanilla JavaScript + HTML/CSS
- **Vision APIs:** Anthropic Claude, OpenAI GPT-4o, or local Ollama
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
