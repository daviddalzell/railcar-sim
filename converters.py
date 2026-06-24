import json
import time
from datetime import datetime

from sqlalchemy import DateTime as SADateTime
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.orm import Session

from models import Car, CommodityCarTypeMap, DispatchPlan, Industry, LayoutSettings, Location, SessionClock, SwitchingArea, Waybill


def waybill_to_dict(w: Waybill) -> dict:
    return {
        "id": w.id,
        "name": w.name,
        "car_id": w.car_id,
        "car_name": (
            f"{w.car.reporting_marks or '—'} {w.car.car_number or ''}".strip()
            if w.car else None
        ),
        "slot_index": w.slot_index,
        "origin_id": w.origin_id,
        "origin_name": w.origin.name if w.origin else None,
        "destination_id": w.destination_id,
        "destination_name": w.destination.name if w.destination else None,
        "industry_id": w.industry_id,
        "industry_name": w.industry.name if w.industry else None,
        "commodity": w.commodity,
        "is_empty": w.is_empty,
        "required_car_type": w.required_car_type,
    }


def car_to_dict(car: Car) -> dict:
    active = next((w for w in car.waybills if w.slot_index == car.active_waybill_slot), None)
    return {
        "id": car.id,
        "car_type": car.car_type,
        "color": car.color,
        "car_number": car.car_number,
        "reporting_marks": car.reporting_marks,
        "photo_path": car.photo_path,
        "current_location_id": car.current_location_id,
        "current_location_name": car.current_location.name if car.current_location else None,
        "active_waybill_slot": car.active_waybill_slot,
        "active_waybill": waybill_to_dict(active) if active else None,
        "waybill_count": len(car.waybills),
    }


def commodity_map_to_dict(m: CommodityCarTypeMap) -> dict:
    return {"id": m.id, "commodity": m.commodity, "car_type": m.car_type}


def industry_to_dict(i: Industry) -> dict:
    return {
        "id": i.id,
        "name": i.name,
        "location_id": i.location_id,
        "location_name": i.location.name if i.location else None,
        "accepted_car_types": i.accepted_car_types,
        "commodities": i.commodities,
        "industry_role": i.industry_role,
        "inbound_car_types": i.inbound_car_types,
        "outbound_commodities": i.outbound_commodities,
        "outbound_car_types": i.outbound_car_types,
    }


def location_to_dict(l: Location) -> dict:
    return {
        "id": l.id,
        "name": l.name,
        "location_type": l.location_type,
        "switching_area_id": l.switching_area_id,
    }


def switching_area_to_dict(area: SwitchingArea, db: Session) -> dict:
    loc_ids = [l.id for l in area.locations]
    current_count = db.query(Car).filter(Car.current_location_id.in_(loc_ids)).count() if loc_ids else 0
    dispatch_ids = {l.id for l in db.query(Location).filter(
        Location.location_type.in_(["staging", "yard"])
    ).all()}
    area_cars = db.query(Car).filter(Car.current_location_id.in_(loc_ids)).all() if loc_ids else []

    def _get_active_waybill(car: Car):
        return next((w for w in car.waybills if w.slot_index == car.active_waybill_slot), None)

    outbound_count = sum(
        1 for car in area_cars
        if (wb := _get_active_waybill(car)) and wb.destination_id in dispatch_ids
    )
    available_spots = max(0, area.car_capacity - current_count + outbound_count)
    return {
        "id": area.id,
        "name": area.name,
        "car_capacity": area.car_capacity,
        "current_car_count": current_count,
        "available_spots": available_spots,
        "locations": [{"id": l.id, "name": l.name, "location_type": l.location_type} for l in area.locations],
    }


def dispatch_plan_to_dict(plan: DispatchPlan, db: Session) -> dict:
    setout_ids = json.loads(plan.setout_ids_json or "[]")
    pickup_ids = json.loads(plan.pickup_ids_json or "[]")
    spots_ids  = json.loads(plan.spots_ids_json or "[]")
    power_ids  = json.loads(plan.power_ids_json or "[]")

    def _enrich(car_id, role):
        car = db.get(Car, car_id)
        if not car:
            return None
        d = car_to_dict(car)
        d["role"] = role
        return d

    setouts     = [d for cid in setout_ids if (d := _enrich(cid, "setout"))]
    pickups     = [d for cid in pickup_ids if (d := _enrich(cid, "pickup"))]
    spots       = [d for cid in spots_ids  if (d := _enrich(cid, "spot"))]
    power_cars  = [d for cid in power_ids  if (d := _enrich(cid, "power"))]
    caboose_car = _enrich(plan.caboose_id, "caboose") if plan.caboose_id else None

    origin = db.get(Location, plan.origin_location_id) if plan.origin_location_id else None
    area = db.get(SwitchingArea, plan.switching_area_id) if plan.switching_area_id else None
    destination = db.get(Location, plan.destination_location_id) if plan.destination_location_id else None

    return {
        "id": plan.id,
        "plan_type": plan.plan_type,
        "status": plan.status or "draft",
        "origin_location_id": plan.origin_location_id,
        "origin_name": origin.name if origin else None,
        "switching_area_id": plan.switching_area_id,
        "switching_area_name": area.name if area else None,
        "destination_location_id": plan.destination_location_id,
        "destination_name": destination.name if destination else None,
        "setouts": setouts,
        "pickups": pickups,
        "spots": spots,
        "power": power_cars,
        "caboose": caboose_car,
        "available_spots": plan.available_spots,
        "built_at": plan.built_at,
        "train_number": plan.train_number,
        "train_name": plan.train_name,
        "departure_time": plan.departure_time,
        "engineer": plan.engineer,
        "conductor": plan.conductor,
        "special_instructions": plan.special_instructions,
        "warnings": [],
    }


def row_to_dict(obj) -> dict:
    result = {}
    for col in sa_inspect(type(obj)).columns:
        val = getattr(obj, col.key)
        if isinstance(val, datetime):
            val = val.isoformat()
        result[col.key] = val
    return result


def get_or_create_settings(db: Session) -> LayoutSettings:
    s = db.get(LayoutSettings, 1)
    if not s:
        s = LayoutSettings(id=1)
        db.add(s)
        db.commit()
        db.refresh(s)
    return s


def settings_to_dict(s: LayoutSettings) -> dict:
    return {
        "clock_start_time": s.clock_start_time,
        "clock_speed": s.clock_speed,
        "ops_mode": s.ops_mode or "free",
    }


def clock_to_dict(c: SessionClock) -> dict:
    return {
        "started_at": c.started_at,
        "paused_at": c.paused_at,
        "paused_accum_s": c.paused_accum_s,
        "start_time": c.start_time,
        "speed": c.speed,
    }


def start_session_clock(db: Session, force: bool = False):
    c = db.get(SessionClock, 1)
    if not force and c and c.started_at is not None:
        return  # clock already running — leave it alone
    s = get_or_create_settings(db)
    if not c:
        c = SessionClock(id=1)
        db.add(c)
    c.started_at = time.time()
    c.paused_at = None
    c.paused_accum_s = 0.0
    c.start_time = s.clock_start_time
    c.speed = s.clock_speed
    db.commit()


def clear_session_clock(db: Session):
    c = db.get(SessionClock, 1)
    if c:
        db.delete(c)
        db.commit()
