# SPDX-FileCopyrightText: 2026 David Dalzell
# SPDX-License-Identifier: MIT

"""Auth dependency safety tests.

Guards the fix for the event-loop hang: the auth dependency must be sync so
FastAPI runs its blocking Supabase/DB calls in a threadpool, and the Supabase
client must carry a timeout so a slow response cannot hang the request.
"""

import inspect

import auth


def test_get_current_user_is_sync():
    """A sync def runs in FastAPI's threadpool. An async def would run the
    blocking Supabase/DB calls on the event loop and could freeze the worker."""
    assert not inspect.iscoroutinefunction(auth.get_current_user)


def test_auth_disabled_returns_synthetic_admin(monkeypatch):
    monkeypatch.setenv("AUTH_DISABLED", "1")
    user = auth.get_current_user(None)
    assert user["role"] == "admin"
    assert user["tenant_slug"] == "local"


def test_auth_supabase_client_configured_with_timeout(monkeypatch):
    """The auth Supabase client must be built with an explicit timeout so a
    slow Supabase response cannot hang indefinitely."""
    import supabase

    captured = {}

    def fake_create_client(url, key, options=None):
        captured["url"] = url
        captured["options"] = options
        return object()

    monkeypatch.setattr(auth, "_supabase", None)
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_KEY", "service-key")
    monkeypatch.setattr(supabase, "create_client", fake_create_client)

    auth._get_supabase()

    assert captured["options"] is not None, "auth client must pass ClientOptions"
    httpx_client = getattr(captured["options"], "httpx_client", None)
    assert httpx_client is not None, "ClientOptions must carry a timeout-bearing httpx client"
    assert httpx_client.timeout is not None
