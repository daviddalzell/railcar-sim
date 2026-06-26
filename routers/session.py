import asyncio
import json
import random
import time
from typing import AsyncGenerator

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from database import get_db
from models import Car, Location, MovementLog, SessionClock, Waybill
from converters import car_to_dict, clock_to_dict, start_session_clock as _start_session_clock, clear_session_clock
from schemas import LayoutSettingsUpdate, SessionEndRequest
from converters import get_or_create_settings, settings_to_dict

router = APIRouter(prefix="/api", tags=["session"])

# ── SSE broadcast ─────────────────────────────────────────────────────────────

_sse_subscribers: set[asyncio.Queue] = set()
_sse_loop: asyncio.AbstractEventLoop | None = None


def _register_loop(loop: asyncio.AbstractEventLoop):
    global _sse_loop
    _sse_loop = loop


def _broadcast_clock(payload: dict | None):
    """Called from sync route handlers to push clock state to all SSE clients."""
    if not _sse_loop:
        return
    data = json.dumps(payload)
    for q in list(_sse_subscribers):
        _sse_loop.call_soon_threadsafe(q.put_nowait, data)


async def _sse_generator(queue: asyncio.Queue) -> AsyncGenerator[str, None]:
    try:
        while True:
            data = await queue.get()
            yield f"data: {data}\n\n"
    except asyncio.CancelledError:
        pass
    finally:
        _sse_subscribers.discard(queue)


def _get_active_waybill(car: Car):
    return next((w for w in car.waybills if w.slot_index == car.active_waybill_slot), None)


def _advance_slot(car: Car) -> tuple[int, bool]:
    """Returns (new_slot, cycle_complete). cycle_complete is True when the car wraps back to slot 0."""
    assigned = sorted(w.slot_index for w in car.waybills if w.slot_index is not None)
    if not assigned:
        return car.active_waybill_slot, False
    try:
        idx = assigned.index(car.active_waybill_slot)
        wrapped = idx == len(assigned) - 1
        return assigned[(idx + 1) % len(assigned)], wrapped
    except ValueError:
        return assigned[0], False


def _build_session_plan(db: Session) -> dict:
    # staging + yard both act as dispatch points (trains originate/terminate there)
    dispatch_ids = {l.id for l in db.query(Location).filter(
        Location.location_type.in_(["staging", "yard"])
    ).all()}
    storage_ids = {l.id for l in db.query(Location).filter(
        Location.location_type == "storage"
    ).all()}
    arrivals, departures, spots, warnings = [], [], [], []

    for car in db.query(Car).all():
        wb = _get_active_waybill(car)
        if not wb or wb.destination_id is None:
            continue
        if car.current_location_id != wb.destination_id:
            if car.current_location_id in dispatch_ids:
                arrivals.append(car)
            elif wb.destination_id in dispatch_ids:
                departures.append(car)
            elif car.current_location_id in storage_ids:
                spots.append(car)
            else:
                departures.append(car)

    random.shuffle(arrivals)
    arrivals = arrivals[:5]
    random.shuffle(departures)
    departures = departures[:min(5, max(len(arrivals), len(departures)))]
    random.shuffle(spots)
    spots = spots[:5]

    if len(departures) < len(arrivals):
        warnings.append(
            f"Only {len(departures)} outbound car(s) available but {len(arrivals)} arrival(s) planned."
        )
    if not arrivals:
        warnings.append("No inbound cars (cars at yard/staging needing a move) available.")
    if not departures:
        warnings.append("No outbound cars (cars at industries needing a move) available.")

    def _enrich(car):
        d = car_to_dict(car)
        wb = _get_active_waybill(car)
        d["session_from_location_name"] = car.current_location.name if car.current_location else None
        d["session_to_location_name"]   = wb.destination.name if wb and wb.destination else None
        return d

    return {
        "arrivals":   [_enrich(c) for c in arrivals],
        "departures": [_enrich(c) for c in departures],
        "spots":      [_enrich(c) for c in spots],
        "warnings":   warnings,
    }


# ── Layout settings ───────────────────────────────────────────────────────────

@router.get("/settings")
def get_settings(db: Session = Depends(get_db)):
    return settings_to_dict(get_or_create_settings(db))


@router.put("/settings")
def update_settings(data: LayoutSettingsUpdate, db: Session = Depends(get_db)):
    s = get_or_create_settings(db)
    s.clock_start_time = data.clock_start_time
    s.clock_speed = data.clock_speed
    s.ops_mode = data.ops_mode
    db.commit()
    return settings_to_dict(s)


# ── Session clock ─────────────────────────────────────────────────────────────

@router.get("/session/clock/events")
async def clock_events():
    queue: asyncio.Queue = asyncio.Queue()
    _sse_subscribers.add(queue)
    return StreamingResponse(
        _sse_generator(queue),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/session/clock")
def get_session_clock(db: Session = Depends(get_db)):
    c = db.get(SessionClock, 1)
    if not c or c.started_at is None:
        return None
    return clock_to_dict(c)


@router.post("/session/clock/pause")
def pause_session_clock(db: Session = Depends(get_db)):
    c = db.get(SessionClock, 1)
    if not c or c.paused_at is not None:
        return {"status": "already paused or no clock"}
    c.paused_at = time.time()
    db.commit()
    result = clock_to_dict(c)
    _broadcast_clock(result)
    return result


@router.post("/session/clock/resume")
def resume_session_clock(db: Session = Depends(get_db)):
    c = db.get(SessionClock, 1)
    if not c or c.paused_at is None:
        return {"status": "not paused"}
    c.paused_accum_s += time.time() - c.paused_at
    c.paused_at = None
    db.commit()
    result = clock_to_dict(c)
    _broadcast_clock(result)
    return result


@router.post("/session/clock/start")
def start_session_clock(db: Session = Depends(get_db)):
    _start_session_clock(db, force=True)
    c = db.get(SessionClock, 1)
    result = clock_to_dict(c)
    _broadcast_clock(result)
    return result


@router.post("/session/clock/ensure")
def ensure_session_clock(db: Session = Depends(get_db)):
    """Start the clock only if it isn't already running. Used when launching sessions so all operators share the same clock."""
    _start_session_clock(db, force=False)
    c = db.get(SessionClock, 1)
    result = clock_to_dict(c) if c else None
    _broadcast_clock(result)
    return result


# ── Session plan / end ────────────────────────────────────────────────────────

@router.post("/session/plan")
def session_plan(db: Session = Depends(get_db)):
    plan = _build_session_plan(db)
    _start_session_clock(db, force=False)
    return plan


@router.post("/session/end")
def session_end(req: SessionEndRequest, db: Session = Depends(get_db)):
    from routers.automation import auto_assign_one_car
    staging_ids = {l.id for l in db.query(Location).filter(
        Location.location_type.in_(["staging", "yard"])
    ).all()}

    updated = []
    for item in req.cars:
        car = db.get(Car, item.car_id)
        if not car:
            continue
        wb = _get_active_waybill(car)
        old_loc = car.current_location_id
        if item.status == "done" and wb and wb.destination_id:
            car.current_location_id = wb.destination_id
            db.add(MovementLog(car_id=car.id, from_location_id=old_loc,
                               to_location_id=wb.destination_id, note="Session move"))
            new_slot, cycle_complete = _advance_slot(car)
            car.active_waybill_slot = new_slot
            car.cp_session_count = 0
            if cycle_complete:
                # Full cycle done — clear all waybills and assign a fresh random route
                for w in list(car.waybills):
                    w.car_id = None
                    w.slot_index = None
                db.flush()
                unassigned = db.query(Waybill).filter(Waybill.car_id.is_(None)).all()
                random.shuffle(unassigned)
                auto_assign_one_car(car, unassigned, staging_ids, db,
                                    starting_loc=car.current_location_id)
                car.active_waybill_slot = 0
        elif item.status == "cp" and item.location_id:
            car.current_location_id = item.location_id
            db.add(MovementLog(car_id=car.id, from_location_id=old_loc,
                               to_location_id=item.location_id, note="Session CP"))
            # waybill NOT advanced for CP cars
            car.cp_session_count = (car.cp_session_count or 0) + 1
        db.commit()
        db.refresh(car)
        updated.append(car_to_dict(car))
    clear_session_clock(db)
    return {"updated": updated}
