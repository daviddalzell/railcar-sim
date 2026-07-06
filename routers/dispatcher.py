# SPDX-FileCopyrightText: 2026 David Dalzell
# SPDX-License-Identifier: MIT

import json
import time

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import nullslast
from sqlalchemy.orm import Session
from starlette.requests import Request

from database import get_db
from models import Car, DispatchPlan, Location, SwitchingArea
from converters import car_to_dict, dispatch_plan_to_dict
from schemas import DispatchBuildRequest, DispatchPlanIdentityUpdate, DispatchPowerUpdate, DispatchPlanStatusUpdate

router = APIRouter(prefix="/api", tags=["dispatcher"])


def _get_active_waybill(car: Car):
    return next((w for w in car.waybills if w.slot_index == car.active_waybill_slot), None)


def _clear_dispatch_plan(db: Session):
    db.query(DispatchPlan).delete(synchronize_session=False)
    db.commit()


def _run_build_algorithm(data_origin_id: int, data_area_id: int, destination_id: int, db: Session) -> tuple:
    """Core build logic. Returns (consist_inbound, outbound, local_spots, available_spots, warnings)."""
    area = db.get(SwitchingArea, data_area_id)
    origin = db.get(Location, data_origin_id)

    area_location_ids = {l.id for l in area.locations}

    # Collect car IDs already claimed by other non-complete plans
    claimed_ids: set = set()
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
        if car.id not in claimed_ids
        and (wb := _get_active_waybill(car)) and wb.destination_id == destination_id
    ]

    local_spots = [
        car for car in area_cars
        if car.id not in claimed_ids
        and (wb := _get_active_waybill(car))
        and wb.destination_id in area_location_ids
        and car.current_location_id != wb.destination_id
    ]

    available_spots = max(0, area.car_capacity - current_count + len(outbound))

    origin_cars = db.query(Car).filter(
        Car.current_location_id == data_origin_id
    ).all()
    inbound = [
        car for car in origin_cars
        if car.id not in claimed_ids
        and (wb := _get_active_waybill(car)) and wb.destination_id in area_location_ids
    ]
    consist_inbound = inbound[:available_spots]

    warnings = []
    left_behind = len(inbound) - len(consist_inbound)
    if left_behind > 0:
        warnings.append(
            f"{left_behind} car{'s' if left_behind != 1 else ''} at origin cannot be delivered — "
            f"{area.name} is at or near capacity ({current_count}/{area.car_capacity} spots used)."
        )
    if not consist_inbound and not outbound and not local_spots:
        warnings.append("No eligible cars found for this origin and switching area.")

    return consist_inbound, outbound, local_spots, available_spots, warnings


def _tenant_slug(request: Request) -> str:
    tenant = getattr(request.state, "tenant", None)
    return getattr(tenant, "slug", None) or "local"


@router.post("/dispatcher/build-plan")
def build_dispatch_plan(request: Request, data: DispatchBuildRequest, db: Session = Depends(get_db)):
    area = db.get(SwitchingArea, data.switching_area_id)
    if not area:
        raise HTTPException(404, "Switching area not found")
    origin = db.get(Location, data.origin_location_id)
    if not origin:
        raise HTTPException(404, "Origin location not found")
    destination = db.get(Location, data.destination_location_id)
    if not destination:
        raise HTTPException(404, "Destination location not found")

    consist_inbound, outbound, local_spots, available_spots, warnings = _run_build_algorithm(
        data.origin_location_id, data.switching_area_id, data.destination_location_id, db
    )

    plan = DispatchPlan(
        plan_type="switching",
        origin_location_id=data.origin_location_id,
        switching_area_id=data.switching_area_id,
        destination_location_id=data.destination_location_id,
        setout_ids_json=json.dumps([c.id for c in consist_inbound]),
        pickup_ids_json=json.dumps([c.id for c in outbound]),
        spots_ids_json=json.dumps([c.id for c in local_spots]),
        available_spots=available_spots,
        built_at=time.time(),
        status="draft",
    )
    db.add(plan)
    db.commit()
    db.refresh(plan)

    result = dispatch_plan_to_dict(plan, db)
    result["warnings"] = warnings

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
def delete_dispatch_plan(plan_id: int, db: Session = Depends(get_db)):
    plan = db.get(DispatchPlan, plan_id)
    if not plan:
        raise HTTPException(404, "Dispatch plan not found")
    db.delete(plan)
    db.commit()


@router.delete("/dispatcher/plans", status_code=204)
def clear_all_dispatch_plans(db: Session = Depends(get_db)):
    _clear_dispatch_plan(db)


@router.patch("/dispatcher/plan/{plan_id}/power")
def update_dispatch_power(plan_id: int, data: DispatchPowerUpdate, db: Session = Depends(get_db)):
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
                              db: Session = Depends(get_db)):
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


@router.post("/dispatcher/plan/{plan_id}/rebuild")
def rebuild_dispatch_plan(plan_id: int, db: Session = Depends(get_db)):
    plan = db.get(DispatchPlan, plan_id)
    if not plan:
        raise HTTPException(404, "Dispatch plan not found")
    if not plan.origin_location_id or not plan.switching_area_id or not plan.destination_location_id:
        raise HTTPException(400, "Plan has no origin, destination, or switching area to rebuild from")

    area = db.get(SwitchingArea, plan.switching_area_id)
    if not area:
        raise HTTPException(404, "Switching area not found")
    origin = db.get(Location, plan.origin_location_id)
    if not origin:
        raise HTTPException(404, "Origin location not found")
    destination = db.get(Location, plan.destination_location_id)
    if not destination:
        raise HTTPException(404, "Destination location not found")

    # Temporarily exclude this plan from claimed IDs so it can rebuild freely
    plan.setout_ids_json = "[]"
    plan.pickup_ids_json = "[]"
    plan.spots_ids_json = "[]"
    db.flush()

    consist_inbound, outbound, local_spots, available_spots, warnings = _run_build_algorithm(
        plan.origin_location_id, plan.switching_area_id, plan.destination_location_id, db
    )

    plan.setout_ids_json = json.dumps([c.id for c in consist_inbound])
    plan.pickup_ids_json = json.dumps([c.id for c in outbound])
    plan.spots_ids_json = json.dumps([c.id for c in local_spots])
    plan.available_spots = available_spots
    plan.built_at = time.time()
    db.commit()

    result = dispatch_plan_to_dict(plan, db)
    result["warnings"] = warnings
    return result
