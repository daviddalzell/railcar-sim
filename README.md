# Rail Car Movement Simulator

A web app for managing a model railroad car roster, waybills, and operations. Optionally uses an AI vision model to identify car details from a photo.

---

## Requirements

- Python 3.11 or later
- (Optional) An API key for your chosen AI vision provider, or a running [Ollama](https://ollama.com) instance for local open-source models

---

## Setup

### 1. Clone the repository

```bash
git clone <repo-url>
cd railcar-sim
```

### 2. Create a virtual environment

```bash
python3 -m venv .venv
source .venv/bin/activate
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Activate the pre-commit hook

```bash
git config core.hooksPath scripts/hooks
```

This runs the test suite before every commit and blocks the commit if any test fails.

### 5. Configure environment variables

Copy the example config file and edit it:

```bash
cp .env.example .env
```

Open `.env` and fill in the values for your chosen vision provider (see [Vision Providers](#vision-providers) below). If you skip this step the app still works — you just fill in car details manually after uploading a photo.

---

## Running the app

```bash
.venv/bin/python3 -m uvicorn main:app --reload
```

Then open [http://localhost:8000](http://localhost:8000) in your browser.

The `--reload` flag restarts the server automatically when you edit source files. Drop it for a stable/production run.

---

## Vision Providers

The app can analyse a photo of a model railroad car and pre-fill the car type, colour, number, and reporting marks. Set `VISION_PROVIDER` in your `.env` file to choose a provider.

### Anthropic (default)

Uses Claude's vision API.

```env
VISION_PROVIDER=anthropic
ANTHROPIC_API_KEY=your-key-here
```

Get a key at [console.anthropic.com](https://console.anthropic.com) → API Keys.

### OpenAI

Uses GPT-4o vision.

```env
VISION_PROVIDER=openai
OPENAI_API_KEY=your-key-here
# OPENAI_MODEL=gpt-4o   # optional, gpt-4o is the default
```

### Ollama (local / open-source)

Runs a vision model locally — no API key required. Install the [Ollama macOS app](https://ollama.com/download/mac) and set:

```env
VISION_PROVIDER=ollama
# OLLAMA_MODEL=llava                          # optional, llava is the default
# OLLAMA_BASE_URL=http://localhost:11434/v1   # optional, this is the default
```

When the app starts it will automatically launch the Ollama daemon if it isn't already running, and pull the configured model if it hasn't been downloaded yet. The first pull may take several minutes depending on model size — progress is printed to the server console.

### No vision provider

If no provider is configured (or the API key is missing), the app still works. After uploading a photo you can fill in the car details manually.

---

## Project structure

```
railcar-sim/
├── main.py              # FastAPI app and API endpoints
├── models.py            # SQLAlchemy database models
├── database.py          # Database connection and setup
├── vision.py            # AI vision provider implementations
├── requirements.txt
├── pytest.ini
├── .env.example         # Configuration template
├── scripts/
│   └── hooks/
│       └── pre-commit   # Git pre-commit hook (activate with step 4 above)
├── static/              # CSS and JavaScript
├── templates/           # HTML template
├── tests/               # Pytest test suite
└── uploads/             # Uploaded car photos (auto-created)
```

---

## Database

The app uses SQLite and creates `railcar.db` automatically in the project root on first run. No database setup is required.
