# SPDX-FileCopyrightText: 2026 David Dalzell
# SPDX-License-Identifier: MIT

"""SSE channel for dispatcher↔crew coordination events.

Broadcasts key session and dispatch plan state changes to all connected
browsers in the same tenant, excluding the tab that triggered the change.

Events: session_started, session_ended, plan_created, plan_crew_changed,
        plan_status_changed.
"""
import asyncio
import json
from typing import AsyncGenerator

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from starlette.requests import Request

import sse_shared

# No auth — browser EventSource cannot send Authorization headers.
router = APIRouter(prefix="/api", tags=["ops_events"])

# Per-tenant set of (sid, queue) tuples.
# sid is the subscriber ID sent by the browser when opening the EventSource.
_subscribers: dict[str, set[tuple[str, asyncio.Queue]]] = {}


def broadcast(
    tenant_slug: str,
    event_type: str,
    payload: dict,
    exclude_sid: str | None = None,
) -> None:
    """Push an ops event to all subscribers in tenant_slug except exclude_sid.

    Safe to call from sync FastAPI route handlers — uses call_soon_threadsafe
    to cross the sync/async boundary.
    """
    loop = sse_shared.get_loop()
    if not loop:
        return
    frame = json.dumps({"type": event_type, **payload})
    for sid, q in list(_subscribers.get(tenant_slug, set())):
        if sid == exclude_sid:
            continue
        loop.call_soon_threadsafe(q.put_nowait, frame)


async def _generator(tenant_slug: str, sid: str) -> AsyncGenerator[str, None]:
    queue: asyncio.Queue = asyncio.Queue()
    entry = (sid, queue)
    _subscribers.setdefault(tenant_slug, set()).add(entry)
    try:
        while True:
            try:
                data = await asyncio.wait_for(queue.get(), timeout=25)
                yield f"data: {data}\n\n"
            except asyncio.TimeoutError:
                yield ": keepalive\n\n"
    except asyncio.CancelledError:
        pass
    finally:
        tenant_subs = _subscribers.get(tenant_slug, set())
        tenant_subs.discard(entry)
        if not tenant_subs:
            _subscribers.pop(tenant_slug, None)


@router.get("/ops/events")
async def ops_events(request: Request):
    tenant = getattr(request.state, "tenant", None)
    slug = getattr(tenant, "slug", None) or "local"
    sid = request.query_params.get("sid", "")
    return StreamingResponse(
        _generator(slug, sid),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
