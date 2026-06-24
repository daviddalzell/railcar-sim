import time

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from database import get_db
from models import Car, Location, MovementLog, SessionClock
from converters import car_to_dict, clock_to_dict, start_session_clock as _start_session_clock, clear_session_clock
from schemas import LayoutSettingsUpdate, SessionEndRequest
from converters import get_or_create_settings, settings_to_dict

router = APIRouter(prefix="/api", tags=["session"])


def _get_active_waybill(car: Car):
    return next((w for w in car.waybills if w.slot_index == car.active_waybill_slot), None)


def _advance_slot(car: Car) -> int:
    assigned = sorted(w.slot_index for w in car.waybills if w.slot_index is not None)
    if not assigned:
        return car.active_waybill_slot
    try:
        idx = assigned.index(car.active_waybill_slot)
        return assigned[(idx + 1) % len(assigned)]
    except ValueError:
        return assigned[0]


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

    arrivals   = sorted(arrivals,   key=lambda c: c.id)[:5]
    departures = sorted(departures, key=lambda c: c.id)[:min(5, max(len(arrivals), len(departures)))]
    spots      = sorted(spots,      key=lambda c: c.id)[:5]

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
    return clock_to_dict(c)


@router.post("/session/clock/resume")
def resume_session_clock(db: Session = Depends(get_db)):
    c = db.get(SessionClock, 1)
    if not c or c.paused_at is None:
        return {"status": "not paused"}
    c.paused_accum_s += time.time() - c.paused_at
    c.paused_at = None
    db.commit()
    return clock_to_dict(c)


@router.post("/session/clock/start")
def start_session_clock(db: Session = Depends(get_db)):
    _start_session_clock(db, force=True)
    c = db.get(SessionClock, 1)
    return clock_to_dict(c)


@router.post("/session/clock/ensure")
def ensure_session_clock(db: Session = Depends(get_db)):
    """Start the clock only if it isn't already running. Used when launching sessions so all operators share the same clock."""
    _start_session_clock(db, force=False)
    c = db.get(SessionClock, 1)
    return clock_to_dict(c) if c else None


# ── Session plan / end ────────────────────────────────────────────────────────

@router.post("/session/plan")
def session_plan(db: Session = Depends(get_db)):
    plan = _build_session_plan(db)
    _start_session_clock(db, force=False)
    return plan


@router.post("/session/end")
def session_end(req: SessionEndRequest, db: Session = Depends(get_db)):
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
            car.active_waybill_slot = _advance_slot(car)
        elif item.status == "cp" and item.location_id:
            car.current_location_id = item.location_id
            db.add(MovementLog(car_id=car.id, from_location_id=old_loc,
                               to_location_id=item.location_id, note="Session CP"))
            # waybill NOT advanced for CP cars
        db.commit()
        db.refresh(car)
        updated.append(car_to_dict(car))
    clear_session_clock(db)
    return {"updated": updated}
