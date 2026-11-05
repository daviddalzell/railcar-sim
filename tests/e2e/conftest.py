"""Shared fixtures for the Playwright e2e suite.

These tests drive a real browser against a real uvicorn server (not the
in-memory `TestClient` the unit suite uses), so this file launches the app as a
subprocess on a fixed port backed by a throwaway SQLite database, waits for it
to answer `/health`, and tears it down afterwards.

Every test here is marked `e2e` (see `pytest_collection_modifyitems`) and is
deselected by the default `-m "not e2e"` in pytest.ini. Run with `pytest -m e2e`.
"""

import os
import subprocess
import sys
import urllib.error
import urllib.request

import pytest

HOST = "127.0.0.1"
PORT = 8811
BASE_URL = f"http://{HOST}:{PORT}"
DB_PATH = "/tmp/wp_e2e.db"


def pytest_collection_modifyitems(items):
    """Mark every test under tests/e2e/ as `e2e` so the suite-wide default
    `-m "not e2e"` skips them unless explicitly requested with `-m e2e`.
    Scoped to this directory — this hook receives all collected items globally."""
    e2e_dir = os.path.dirname(__file__)
    for item in items:
        if str(item.path).startswith(e2e_dir):
            item.add_marker(pytest.mark.e2e)


def _wait_for_health(proc, timeout=30.0):
    import time

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            raise RuntimeError(
                f"uvicorn exited early with code {proc.returncode} before becoming healthy"
            )
        try:
            with urllib.request.urlopen(f"{BASE_URL}/health", timeout=1) as resp:
                if resp.status == 200:
                    return
        except (urllib.error.URLError, ConnectionError, OSError):
            pass
        time.sleep(0.25)
    raise RuntimeError(f"server did not become healthy within {timeout}s")


@pytest.fixture(scope="session")
def live_server():
    """Launch `uvicorn main:app` on a fresh SQLite DB, yield its base URL, stop it."""
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)

    env = {
        **os.environ,
        "AUTH_DISABLED": "1",
        "DATABASE_URL": f"sqlite:///{DB_PATH}",
        # Clear any inherited Supabase config so the app stays in local/SQLite mode.
        "SUPABASE_URL": "",
        "SUPABASE_ANON_KEY": "",
        "SUPABASE_KEY": "",
    }
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "main:app", "--host", HOST, "--port", str(PORT)],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    try:
        _wait_for_health(proc)
        yield BASE_URL
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()


@pytest.fixture(scope="session")
def base_url(live_server):
    """Override pytest-playwright's base_url so page.goto('/') hits the live server."""
    return live_server
