# SPDX-FileCopyrightText: 2026 David Dalzell
# SPDX-License-Identifier: MIT

import json
import time

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import nullslast
from sqlalchemy.orm import Session
from starlette.requests import Request

from auth import require_admin
from database import get_db
from models import Car, DispatchPlan, Industry, Location, Track
from converters import car_to_dict, dispatch_plan_to_dict, get_or_create_settings
from schemas import (
    DispatchBuildRequest, DispatchPlanIdentityUpdate, DispatchPowerUpdate,
    DispatchPlanStatusUpdate, DispatchRebuildRequest,
)

router = APIRouter(prefix="/api", tags=["dispatcher"])


_POWER_CAR_TYPES = {"locomotive", "caboose"}  # matches the string convention already
# used client-side (static/js/operations.js's power/caboose selects) and in
# converters.py's "caboose" role tag — no CarType.is_power flag exists to reuse instead.


def _get_active_waybill(car: Car):
    return next((w for w in car.waybills if w.slot_index == car.active_waybill_slot), None)


def _clear_dispatch_plan(db: Session):
    db.query(DispatchPlan).delete(synchronize_session=False)
    db.commit()


def _run_build_algorithm(data_origin_id: int, data_area_id: int, destination_id: int, db: Session,
                          excluded_car_ids=frozenset()) -> tuple:
    """Core build logic. Returns (consist_inbound, outbound, local_spots, available_spots, warnings).

    excluded_car_ids: cars a human removed from this specific preview before confirming —
    request-scoped only, never persisted. Cars can only be removed before a plan is
    committed; once built, a consist's car list is fixed until the next Rebuild.
    """
    area = db.get(Location, data_area_id)
    origin = db.get(Track, data_origin_id)

    area_location_ids = {t.id for t in area.tracks}
    dispatch_ids = {t.id for t in db.query(Track).filter(
        Track.location_type.in_(["staging", "yard"])
    ).all()}

    # Collect car IDs already claimed by other non-complete plans, plus this call's
    # own request-scoped exclusions.
    claimed_ids: set = set(excluded_car_ids)
    for other in db.query(DispatchPlan).filter(DispatchPlan.status != "complete").all():
        claimed_ids |= set(json.loads(other.setout_ids_json or "[]"))
        claimed_ids |= set(json.loads(other.pickup_ids_json or "[]"))
        claimed_ids |= set(json.loads(other.spots_ids_json or "[]"))

    current_count = db.query(Car).filter(
        Car.current_location_id.in_(list(area_location_ids))
    ).count() if area_location_ids else 0

    area_cars = db.query(Car).filter(
        Car.current_location_id.in_(list(area_location_ids))
    ).all() if area_location_ids else []

    outbound = [
        car for car in area_cars
        if car.car_type not in _POWER_CAR_TYPES
        and car.id not in claimed_ids
        and (wb := _get_active_waybill(car)) and wb.destination_id in dispatch_ids
    ]

    local_spots = [
        car for car in area_cars
        if car.car_type not in _POWER_CAR_TYPES
        and car.id not in claimed_ids
        and (wb := _get_active_waybill(car))
        and wb.destination_id in area_location_ids
        and car.current_location_id != wb.destination_id
    ]
    local_spots = local_spots[:round(area.car_capacity * 0.375)]

    available_spots = max(0, area.car_capacity - current_count + len(outbound))

    origin_cars = db.query(Car).filter(
        Car.current_location_id == data_origin_id
    ).all()
    inbound = [
        car for car in origin_cars
        if car.car_type not in _POWER_CAR_TYPES
        and car.id not in claimed_ids
        and (wb := _get_active_waybill(car)) and wb.destination_id in area_location_ids
    ]

    # Max train length: a hard cap on how many NEW cars can board (outbound/local_spots
    # are already-committed existing-in-area traffic, not discretionary additions).
    settings = get_or_create_settings(db)
    inbound_cap = available_spots
    if settings.max_train_length is not None:
        inbound_cap = min(inbound_cap, max(0, settings.max_train_length - len(outbound) - len(local_spots)))
    consist_inbound = inbound[:inbound_cap]

    # Pulls before puts: a siding isn't full if its occupant is leaving on this same
    # trip, so net out same-visit pulls (outbound leaves the area; local_spots leaves
    # its current track for a different one in the area) before checking what fits.
    occupancy_by_track: dict = {}
    for car in area_cars:
        occupancy_by_track[car.current_location_id] = occupancy_by_track.get(car.current_location_id, 0) + 1

    pulled_from_track: dict = {}
    pulled_from_industry: dict = {}
    for car in outbound + local_spots:
        pulled_from_track[car.current_location_id] = pulled_from_track.get(car.current_location_id, 0) + 1
        wb = _get_active_waybill(car)
        if wb and wb.industry_id:
            pulled_from_industry[wb.industry_id] = pulled_from_industry.get(wb.industry_id, 0) + 1

    net_occupancy_by_track = {
        tid: max(0, n - pulled_from_track.get(tid, 0)) for tid, n in occupancy_by_track.items()
    }

    # Track capacity is a soft limit: it informs a "will need CP" warning but never
    # removes a car from the plan. Location.car_capacity (already enforced above via
    # available_spots and the local_spots cap) is the only thing that can leave a car
    # at origin — a car whose specific siding is tight still rides along if the area
    # itself has room, same as how industry-capacity overflow already works below.
    track_baseline = dict(net_occupancy_by_track)  # occupancy after pulls, before this visit's arrivals
    track_overflow: dict = {}  # track_id -> count of cars over that track's capacity
    for car in consist_inbound + local_spots:
        wb = _get_active_waybill(car)
        track = db.get(Track, wb.destination_id)
        if not track:
            continue
        net_occupancy_by_track[track.id] = net_occupancy_by_track.get(track.id, 0) + 1
        if track.car_capacity is not None and net_occupancy_by_track[track.id] > track.car_capacity:
            track_overflow[track.id] = track_overflow.get(track.id, 0) + 1

    # Industry spot capacity: same soft-limit treatment, pulls-netted the same way.
    by_industry: dict = {}
    for car in consist_inbound + local_spots:
        wb = _get_active_waybill(car)
        if wb and wb.industry_id:
            by_industry.setdefault(wb.industry_id, []).append(car)

    industry_warnings = []
    for industry_id, incoming in by_industry.items():
        industry = db.get(Industry, industry_id)
        if not industry:
            continue
        spot_nums = [s for s in (industry.spot_numbers or "").split(",") if s.strip()]
        if not spot_nums:
            continue
        capacity = len(spot_nums)
        current_count_at_industry = sum(
            1 for c in area_cars
            if c.current_location_id == industry.location_id
            and (wb := _get_active_waybill(c)) and wb.industry_id == industry.id
        )
        net_current = max(0, current_count_at_industry - pulled_from_industry.get(industry.id, 0))
        if net_current + len(incoming) > capacity:
            over = net_current + len(incoming) - capacity
            industry_warnings.append(
                f"{industry.name}: {over} car{'s' if over != 1 else ''} will need temporary CP "
                f"placement ({net_current} of {capacity} spot{'s' if capacity != 1 else ''} already in use)."
            )

    # Destination mismatch: outbound cars are matched against any yard/staging track
    # layout-wide (not just the chosen destination) — see git history ce41f32/f0a150c for
    # why that's broad by design. Surface a warning instead of narrowing the match.
    destination_mismatch = sum(
        1 for car in outbound
        if (wb := _get_active_waybill(car)) and wb.destination_id != destination_id
    )
    destination_warning = None
    if destination_mismatch:
        destination = db.get(Track, destination_id)
        dest_name = destination.name if destination else "the selected destination"
        destination_warning = (
            f"{destination_mismatch} outbound car{'s' if destination_mismatch != 1 else ''} "
            f"headed for a different yard/staging track than {dest_name}."
        )

    warnings = []
    left_behind_capacity = len(inbound) - min(len(inbound), available_spots)
    if left_behind_capacity > 0:
        warnings.append(
            f"{left_behind_capacity} car{'s' if left_behind_capacity != 1 else ''} at origin cannot be "
            f"delivered — {area.name} is at or near capacity ({current_count}/{area.car_capacity} spots used)."
        )
    left_behind_length_only = max(0, (len(inbound) - len(consist_inbound)) - left_behind_capacity)
    if left_behind_length_only > 0:
        warnings.append(
            f"{left_behind_length_only} car{'s' if left_behind_length_only != 1 else ''} at origin cannot "
            f"be delivered — train is at its {settings.max_train_length}-car length limit."
        )
    for track_id, over in track_overflow.items():
        track = db.get(Track, track_id)
        in_use = track_baseline.get(track_id, 0)
        warnings.append(
            f"{track.name}: {over} car{'s' if over != 1 else ''} will need temporary CP "
            f"placement (track holds {track.car_capacity}, {in_use} already in use)."
        )
    warnings.extend(industry_warnings)
    if destination_warning:
        warnings.append(destination_warning)
    if not consist_inbound and not outbound and not local_spots:
        warnings.append("No eligible cars found for this origin and switching area.")
    total_work = len(consist_inbound) + len(outbound) + len(local_spots)
    work_threshold = round(area.car_capacity * 0.75)
    if total_work > work_threshold:
        warnings.append(
            f"Large switch list ({total_work} car moves, limit {work_threshold} for this area). "
            "Consider regenerating for a shorter session, or plan for two yard trips."
        )

    return consist_inbound, outbound, local_spots, available_spots, warnings


def _tenant_slug(request: Request) -> str:
    tenant = getattr(request.state, "tenant", None)
    return getattr(tenant, "slug", None) or "local"


@router.post("/dispatcher/build-plan")
def build_dispatch_plan(request: Request, data: DispatchBuildRequest, db: Session = Depends(get_db), _: dict = Depends(require_admin)):
    area = db.get(Location, data.location_id)
    if not area:
        raise HTTPException(404, "Location not found")
    origin = db.get(Track, data.origin_location_id)
    if not origin:
        raise HTTPException(404, "Origin track not found")
    destination = db.get(Track, data.destination_location_id)
    if not destination:
        raise HTTPException(404, "Destination track not found")

    consist_inbound, outbound, local_spots, available_spots, warnings = _run_build_algorithm(
        data.origin_location_id, data.location_id, data.destination_location_id, db,
        excluded_car_ids=set(data.excluded_car_ids),
    )

    plan = DispatchPlan(
        plan_type="switching",
        origin_location_id=data.origin_location_id,
        location_id=data.location_id,
        destination_location_id=data.destination_location_id,
        setout_ids_json=json.dumps([c.id for c in consist_inbound]),
        pickup_ids_json=json.dumps([c.id for c in outbound]),
        spots_ids_json=json.dumps([c.id for c in local_spots]),
        available_spots=available_spots,
        built_at=time.time(),
        status="draft",
        warnings_json=json.dumps(warnings),
    )
    db.add(plan)
    db.commit()
    db.refresh(plan)

    result = dispatch_plan_to_dict(plan, db)

    from routers import ops_events
    car_count = (len(json.loads(plan.setout_ids_json or "[]"))
                 + len(json.loads(plan.pickup_ids_json or "[]"))
                 + len(json.loads(plan.spots_ids_json or "[]")))
    ops_events.broadcast(
        _tenant_slug(request), "plan_created",
        {"plan_id": plan.id, "train_number": plan.train_number or "",
         "train_name": plan.train_name or "", "car_count": car_count},
        exclude_sid=request.headers.get("X-Subscriber-Id", ""),
    )
    return result


@router.post("/dispatcher/preview-plan")
def preview_dispatch_plan(data: DispatchBuildRequest, db: Session = Depends(get_db), _: dict = Depends(require_admin)):
    """Read-only dry run of the build algorithm — no DispatchPlan row is created."""
    area = db.get(Location, data.location_id)
    if not area:
        raise HTTPException(404, "Location not found")
    origin = db.get(Track, data.origin_location_id)
    if not origin:
        raise HTTPException(404, "Origin track not found")
    destination = db.get(Track, data.destination_location_id)
    if not destination:
        raise HTTPException(404, "Destination track not found")

    consist_inbound, outbound, local_spots, available_spots, warnings = _run_build_algorithm(
        data.origin_location_id, data.location_id, data.destination_location_id, db
    )
    return {
        "inbound": [car_to_dict(c) for c in consist_inbound],
        "outbound": [car_to_dict(c) for c in outbound],
        "local_spots": [car_to_dict(c) for c in local_spots],
        "available_spots": available_spots,
        "warnings": warnings,
    }


@router.get("/dispatcher/plans")
def list_dispatch_plans(db: Session = Depends(get_db)):
    plans = db.query(DispatchPlan).order_by(nullslast(DispatchPlan.departure_time), DispatchPlan.id).all()
    return [dispatch_plan_to_dict(p, db) for p in plans]


@router.get("/dispatcher/plan/{plan_id}")
def get_dispatch_plan(plan_id: int, db: Session = Depends(get_db)):
    plan = db.get(DispatchPlan, plan_id)
    if not plan:
        raise HTTPException(404, "Dispatch plan not found")
    return dispatch_plan_to_dict(plan, db)


@router.delete("/dispatcher/plan/{plan_id}", status_code=204)
def delete_dispatch_plan(plan_id: int, db: Session = Depends(get_db), _: dict = Depends(require_admin)):
    plan = db.get(DispatchPlan, plan_id)
    if not plan:
        raise HTTPException(404, "Dispatch plan not found")
    db.delete(plan)
    db.commit()


@router.delete("/dispatcher/plans", status_code=204)
def clear_all_dispatch_plans(db: Session = Depends(get_db), _: dict = Depends(require_admin)):
    _clear_dispatch_plan(db)


@router.patch("/dispatcher/plan/{plan_id}/power")
def update_dispatch_power(plan_id: int, data: DispatchPowerUpdate, db: Session = Depends(get_db), _: dict = Depends(require_admin)):
    plan = db.get(DispatchPlan, plan_id)
    if not plan:
        raise HTTPException(404, "Dispatch plan not found")
    # Exclusivity check
    other_plans = db.query(DispatchPlan).filter(DispatchPlan.id != plan_id).all()
    for other in other_plans:
        other_power = set(json.loads(other.power_ids_json or "[]"))
        conflicts = set(data.power_ids) & other_power
        if conflicts:
            raise HTTPException(409, "Locomotive(s) already assigned to another consist")
        if data.caboose_id and data.caboose_id == other.caboose_id:
            raise HTTPException(409, "Caboose already assigned to another consist")
    plan.power_ids_json = json.dumps(data.power_ids)
    plan.caboose_id = data.caboose_id
    db.commit()
    return dispatch_plan_to_dict(plan, db)


@router.patch("/dispatcher/plan/{plan_id}/identity")
def update_dispatch_identity(request: Request, plan_id: int, data: DispatchPlanIdentityUpdate,
                              db: Session = Depends(get_db), _: dict = Depends(require_admin)):
    plan = db.get(DispatchPlan, plan_id)
    if not plan:
        raise HTTPException(404, "Dispatch plan not found")
    for field, value in data.model_dump(exclude_none=False).items():
        setattr(plan, field, value)
    db.commit()
    result = dispatch_plan_to_dict(plan, db)
    # Only broadcast when engineer or conductor was set (not just train number/name changes)
    if data.engineer or data.conductor:
        from routers import ops_events
        ops_events.broadcast(
            _tenant_slug(request), "plan_crew_changed",
            {"plan_id": plan.id, "train_number": plan.train_number or "",
             "engineer": plan.engineer or "", "conductor": plan.conductor or ""},
            exclude_sid=request.headers.get("X-Subscriber-Id", ""),
        )
    return result


@router.patch("/dispatcher/plan/{plan_id}/status")
def update_dispatch_status(request: Request, plan_id: int, data: DispatchPlanStatusUpdate,
                            db: Session = Depends(get_db)):
    plan = db.get(DispatchPlan, plan_id)
    if not plan:
        raise HTTPException(404, "Dispatch plan not found")
    if data.status not in ("draft", "active", "complete"):
        raise HTTPException(400, "status must be draft, active, or complete")
    plan.status = data.status
    db.commit()
    result = dispatch_plan_to_dict(plan, db)
    if data.status in ("active", "complete"):
        from routers import ops_events
        ops_events.broadcast(
            _tenant_slug(request), "plan_status_changed",
            {"plan_id": plan.id, "train_number": plan.train_number or "",
             "train_name": plan.train_name or "", "status": data.status},
            exclude_sid=request.headers.get("X-Subscriber-Id", ""),
        )
    return result


@router.post("/dispatcher/plan/{plan_id}/preview-rebuild")
def preview_rebuild_dispatch_plan(plan_id: int, db: Session = Depends(get_db), _: dict = Depends(require_admin)):
    """Read-only dry run of a rebuild — the plan's stored car lists are never overwritten."""
    plan = db.get(DispatchPlan, plan_id)
    if not plan:
        raise HTTPException(404, "Dispatch plan not found")
    if not plan.origin_location_id or not plan.location_id or not plan.destination_location_id:
        raise HTTPException(400, "Plan has no origin, destination, or location to rebuild from")

    area = db.get(Location, plan.location_id)
    if not area:
        raise HTTPException(404, "Location not found")
    origin = db.get(Track, plan.origin_location_id)
    if not origin:
        raise HTTPException(404, "Origin track not found")
    destination = db.get(Track, plan.destination_location_id)
    if not destination:
        raise HTTPException(404, "Destination track not found")

    # Temporarily exclude this plan's own cars from "claimed" so it previews its own
    # rebuild correctly. Never committed — the request's session is closed without a
    # commit, so this never persists (mirrors rebuild_dispatch_plan's own clear-before-
    # rebuild step, minus the final commit).
    plan.setout_ids_json = "[]"
    plan.pickup_ids_json = "[]"
    plan.spots_ids_json = "[]"
    db.flush()

    consist_inbound, outbound, local_spots, available_spots, warnings = _run_build_algorithm(
        plan.origin_location_id, plan.location_id, plan.destination_location_id, db
    )
    return {
        "inbound": [car_to_dict(c) for c in consist_inbound],
        "outbound": [car_to_dict(c) for c in outbound],
        "local_spots": [car_to_dict(c) for c in local_spots],
        "available_spots": available_spots,
        "warnings": warnings,
    }


@router.post("/dispatcher/plan/{plan_id}/rebuild")
def rebuild_dispatch_plan(plan_id: int, data: DispatchRebuildRequest = DispatchRebuildRequest(),
                           db: Session = Depends(get_db), _: dict = Depends(require_admin)):
    plan = db.get(DispatchPlan, plan_id)
    if not plan:
        raise HTTPException(404, "Dispatch plan not found")
    if not plan.origin_location_id or not plan.location_id or not plan.destination_location_id:
        raise HTTPException(400, "Plan has no origin, destination, or location to rebuild from")

    area = db.get(Location, plan.location_id)
    if not area:
        raise HTTPException(404, "Location not found")
    origin = db.get(Track, plan.origin_location_id)
    if not origin:
        raise HTTPException(404, "Origin track not found")
    destination = db.get(Track, plan.destination_location_id)
    if not destination:
        raise HTTPException(404, "Destination track not found")

    # Temporarily exclude this plan from claimed IDs so it can rebuild freely
    plan.setout_ids_json = "[]"
    plan.pickup_ids_json = "[]"
    plan.spots_ids_json = "[]"
    db.flush()

    consist_inbound, outbound, local_spots, available_spots, warnings = _run_build_algorithm(
        plan.origin_location_id, plan.location_id, plan.destination_location_id, db,
        excluded_car_ids=set(data.excluded_car_ids),
    )

    plan.setout_ids_json = json.dumps([c.id for c in consist_inbound])
    plan.pickup_ids_json = json.dumps([c.id for c in outbound])
    plan.spots_ids_json = json.dumps([c.id for c in local_spots])
    plan.available_spots = available_spots
    plan.built_at = time.time()
    plan.warnings_json = json.dumps(warnings)
    db.commit()

    result = dispatch_plan_to_dict(plan, db)
    return result
