# SPDX-FileCopyrightText: 2026 David Dalzell
# SPDX-License-Identifier: MIT

"""Shared asyncio event-loop reference for SSE broadcast functions.

Both session.py (clock channel) and ops_events.py (ops channel) need to
call loop.call_soon_threadsafe() from sync route handlers. This module
holds the single loop reference registered at startup so neither router
has to import the other.
"""
import asyncio

_sse_loop: asyncio.AbstractEventLoop | None = None


def register_loop(loop: asyncio.AbstractEventLoop) -> None:
    global _sse_loop
    _sse_loop = loop


def get_loop() -> asyncio.AbstractEventLoop | None:
    return _sse_loop
