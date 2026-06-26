import random
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from database import get_db
from models import Car, CommodityCarTypeMap, Industry, Location, Waybill
from converters import car_to_dict, waybill_to_dict
from schemas import GenerateWaybillsRequest

router = APIRouter(prefix="/api", tags=["automation"])

_WILDCARD_TYPES = {"all", "any", ""}
_ALWAYS_EMPTY_RETURN_TYPES = {"tank car", "hopper", "covered hopper"}


def _car_type_matches(required: Optional[str], car_type: str) -> bool:
    if not required or required.lower() in _WILDCARD_TYPES:
        return True
    return required.lower() == car_type.lower()


def _find_loaded_from(unassigned, location_id, car_type):
    return next(
        (w for w in unassigned
         if not w.is_empty
         and w.origin_id == location_id
         and w.destination_id is not None
         and _car_type_matches(w.required_car_type, car_type)),
        None,
    )


def _find_empty_to_staging(unassigned, location_id, staging_ids, car_type):
    return next(
        (w for w in unassigned
         if w.is_empty
         and w.origin_id == location_id
         and w.destination_id in staging_ids
         and _car_type_matches(w.required_car_type, car_type)),
        None,
    )


def _find_any_from(unassigned, location_id, car_type):
    return next(
        (w for w in unassigned
         if w.origin_id == location_id
         and w.destination_id is not None
         and _car_type_matches(w.required_car_type, car_type)),
        None,
    )


def _find_best_staging_for_car(unassigned, staging_ids, car_type, loaded_only=False):
    counts = {}
    for w in unassigned:
        if loaded_only and w.is_empty:
            continue
        if (w.origin_id in staging_ids
                and w.destination_id is not None
                and _car_type_matches(w.required_car_type, car_type)):
            # Loaded waybills score higher so the car starts where real work is available
            weight = 2 if not w.is_empty else 1
            counts[w.origin_id] = counts.get(w.origin_id, 0) + weight
    if not counts:
        return None
    return max(counts, key=lambda k: counts[k])


def _clone_waybill(source, car, slot: int, db: Session):
    clone = Waybill(
        name=source.name,
        origin_id=source.origin_id,
        destination_id=source.destination_id,
        industry_id=source.industry_id,
        commodity=source.commodity,
        required_car_type=source.required_car_type,
        is_empty=source.is_empty,
        car_id=car.id,
        slot_index=slot,
    )
    db.add(clone)
    db.flush()
    return clone


def _fallback_candidate(db: Session, current_loc: int, staging_ids: set, car_type: str, always_empty: bool):
    """Search all waybills (including assigned) for a route to clone when the unassigned pool is exhausted."""
    if current_loc in staging_ids:
        candidates = db.query(Waybill).filter(
            Waybill.origin_id == current_loc,
            Waybill.is_empty == False,
            Waybill.destination_id.isnot(None),
        ).limit(20).all()
    elif always_empty:
        candidates = db.query(Waybill).filter(
            Waybill.origin_id == current_loc,
            Waybill.is_empty == True,
            Waybill.destination_id.in_(list(staging_ids)),
        ).limit(20).all()
    else:
        candidates = db.query(Waybill).filter(
            Waybill.origin_id == current_loc,
            Waybill.destination_id.isnot(None),
        ).limit(20).all()
    for w in candidates:
        if _car_type_matches(w.required_car_type, car_type):
            return w
    return None


def _fallback_starting_loc(db: Session, staging_ids: set, car_type: str):
    """When the unassigned pool has no staging-origin waybills, query all waybills for one to seed routing."""
    candidates = db.query(Waybill).filter(
        Waybill.origin_id.in_(list(staging_ids)),
        Waybill.is_empty == False,
        Waybill.destination_id.isnot(None),
    ).limit(20).all()
    for w in candidates:
        if _car_type_matches(w.required_car_type, car_type):
            return w.origin_id
    return None


def auto_assign_one_car(car, unassigned: list, staging_ids: set, db: Session, starting_loc=None) -> int:
    """Fill open waybill slots for a single car. Returns number of slots filled.
    Mutates `unassigned` in place (removes assigned loaded waybills).
    Falls back to cloning existing waybills when the pool is exhausted so all 4 slots are always filled."""
    occupied = {w.slot_index for w in car.waybills if w.slot_index is not None}
    open_slots = [s for s in range(4) if s not in occupied]
    if not open_slots:
        return 0

    random.shuffle(unassigned)

    always_empty = any(t in car.car_type.lower() for t in _ALWAYS_EMPTY_RETURN_TYPES)

    if not car.waybills:
        if starting_loc is not None:
            current_loc = starting_loc
        else:
            current_loc = _find_best_staging_for_car(unassigned, staging_ids, car.car_type, loaded_only=always_empty)
            if current_loc is None:
                current_loc = _fallback_starting_loc(db, staging_ids, car.car_type)
        if current_loc is None:
            return 0
    else:
        filled = sorted(w.slot_index for w in car.waybills if w.slot_index is not None)
        last = filled[-1]
        expected = list(range(last + 1, last + 1 + len(open_slots)))
        if open_slots != expected:
            return 0
        last_wb = next((w for w in car.waybills if w.slot_index == last), None)
        if last_wb is None or last_wb.destination_id is None:
            return 0
        current_loc = last_wb.destination_id

    assigned = 0
    for slot in open_slots:
        if current_loc in staging_ids:
            if always_empty:
                candidate = _find_loaded_from(unassigned, current_loc, car.car_type)
            else:
                candidate = _find_any_from(unassigned, current_loc, car.car_type)
        elif always_empty:
            candidate = _find_empty_to_staging(unassigned, current_loc, staging_ids, car.car_type)
        else:
            candidate = (
                _find_loaded_from(unassigned, current_loc, car.car_type)
                or _find_empty_to_staging(unassigned, current_loc, staging_ids, car.car_type)
            )

        if candidate is None:
            candidate = _fallback_candidate(db, current_loc, staging_ids, car.car_type, always_empty)
            if candidate is None:
                break
            _clone_waybill(candidate, car, slot, db)
            assigned += 1
            current_loc = candidate.destination_id
            if current_loc is None:
                break
            continue

        if candidate.is_empty:
            _clone_waybill(candidate, car, slot, db)
        else:
            candidate.car_id = car.id
            candidate.slot_index = slot
            unassigned.remove(candidate)

        assigned += 1
        current_loc = candidate.destination_id
        if current_loc is None:
            break

    return assigned


def clear_car_slots(car, db: Session):
    """Unassign all waybill slots from a car, returning loaded waybills to the pool.
    Cloned empty waybills are deleted (they have no independent pool entry).
    Resets active_waybill_slot to 0 so the fresh assignment starts at the beginning."""
    for wb in list(car.waybills):
        if wb.is_empty:
            db.delete(wb)
        else:
            wb.car_id = None
            wb.slot_index = None
    car.active_waybill_slot = 0
    db.commit()


@router.post("/generate-waybills")
def generate_waybills(data: GenerateWaybillsRequest, db: Session = Depends(get_db)):
    if data.replace:
        db.query(Waybill).delete(synchronize_session=False)
        db.commit()

    # Generate waybills for every staging and yard location so cars at any
    # dispatch point get full inbound/outbound/empty routes.
    origin_locations = db.query(Location).filter(
        Location.location_type.in_(["staging", "yard"])
    ).all()
    if not origin_locations:
        return {"created": 0, "skipped": 0, "waybills": []}

    industries = db.query(Industry).all()
    map_rows = db.query(CommodityCarTypeMap).all()
    commodity_map = {r.commodity: r.car_type for r in map_rows}

    created = 0
    skipped = 0
    new_waybills = []

    def parse_csv(s):
        return [t.strip() for t in (s or "").split(",") if t.strip()]

    def fallback_type(types):
        t = [x for x in types if x.lower() not in _WILDCARD_TYPES]
        return t[0] if t else None

    def _wb_exists(name, ind_id, origin_id):
        return db.query(Waybill).filter(
            Waybill.industry_id == ind_id,
            Waybill.name == name,
            Waybill.origin_id == origin_id,
        ).first()

    def _add(wb):
        nonlocal created
        db.add(wb)
        db.flush()
        new_waybills.append(wb)
        created += 1

    for ind in industries:
        if not ind.location_id:
            continue
        role = getattr(ind, "industry_role", "consumer")

        # Inbound fields: commodities + car types for receiving direction
        inbound_commodities = parse_csv(ind.commodities)
        inbound_raw_types   = parse_csv(ind.inbound_car_types or ind.accepted_car_types)
        inbound_fallback    = fallback_type(inbound_raw_types)

        # Outbound fields: commodities + car types for shipping direction
        outbound_commodities = parse_csv(ind.outbound_commodities or ind.commodities)
        outbound_raw_types   = parse_csv(ind.outbound_car_types or ind.accepted_car_types)
        outbound_fallback    = fallback_type(outbound_raw_types)

        has_inbound  = role in ("consumer", "transload")
        has_outbound = role in ("producer", "transload")

        if not inbound_commodities and not outbound_commodities:
            continue

        inbound_empty_types  = [ct for ct in inbound_raw_types  if ct.lower() not in _WILDCARD_TYPES]
        outbound_empty_types = [ct for ct in outbound_raw_types if ct.lower() not in _WILDCARD_TYPES]

        for origin_loc in origin_locations:
            origin_id = origin_loc.id

            # Inbound loaded waybills (staging/yard → industry)
            if has_inbound:
                for commodity in inbound_commodities:
                    req_type = commodity_map.get(commodity.lower(), inbound_fallback)
                    in_name = f"{commodity} → {ind.name}"
                    if not _wb_exists(in_name, ind.id, origin_id):
                        _add(Waybill(
                            name=in_name,
                            origin_id=origin_id,
                            destination_id=ind.location_id,
                            industry_id=ind.id,
                            commodity=commodity,
                            required_car_type=req_type,
                            is_empty=False,
                        ))
                    else:
                        skipped += 1

            # Outbound loaded waybills (industry → staging/yard)
            if has_outbound:
                for commodity in outbound_commodities:
                    req_type = commodity_map.get(commodity.lower(), outbound_fallback)
                    out_name = f"{commodity} ← {ind.name}"
                    if not _wb_exists(out_name, ind.id, ind.location_id):
                        _add(Waybill(
                            name=out_name,
                            origin_id=ind.location_id,
                            destination_id=origin_id,
                            industry_id=ind.id,
                            commodity=commodity,
                            required_car_type=req_type,
                            is_empty=False,
                        ))
                    else:
                        skipped += 1

            # Empty return waybills (industry → staging/yard), one per inbound car type per origin
            if inbound_empty_types:
                for ct in inbound_empty_types:
                    n = f"← {ind.name} (empty {ct})"
                    if not _wb_exists(n, ind.id, ind.location_id):
                        _add(Waybill(name=n, origin_id=ind.location_id,
                            destination_id=origin_id, industry_id=ind.id,
                            commodity="", required_car_type=ct, is_empty=True))
                    else:
                        skipped += 1
            elif has_inbound:
                n = f"← {ind.name} (empty)"
                if not _wb_exists(n, ind.id, ind.location_id):
                    _add(Waybill(name=n, origin_id=ind.location_id,
                        destination_id=origin_id, industry_id=ind.id,
                        commodity="", required_car_type=None, is_empty=True))
                else:
                    skipped += 1

            # Empty delivery waybills (staging/yard → industry), one per outbound car type per origin
            if has_outbound:
                if outbound_empty_types:
                    for ct in outbound_empty_types:
                        n = f"→ {ind.name} (empty {ct})"
                        if not _wb_exists(n, ind.id, origin_id):
                            _add(Waybill(name=n, origin_id=origin_id,
                                destination_id=ind.location_id, industry_id=ind.id,
                                commodity="", required_car_type=ct, is_empty=True))
                        else:
                            skipped += 1
                else:
                    n = f"→ {ind.name} (empty)"
                    if not _wb_exists(n, ind.id, origin_id):
                        _add(Waybill(name=n, origin_id=origin_id,
                            destination_id=ind.location_id, industry_id=ind.id,
                            commodity="", required_car_type=outbound_fallback, is_empty=True))
                    else:
                        skipped += 1

    db.commit()
    for w in new_waybills:
        db.refresh(w)
    return {"created": created, "skipped": skipped, "waybills": [waybill_to_dict(w) for w in new_waybills]}


@router.post("/auto-assign-waybills")
def auto_assign_waybills(db: Session = Depends(get_db)):
    cars = db.query(Car).all()
    unassigned = db.query(Waybill).filter(Waybill.car_id.is_(None)).all()

    staging_ids = {
        loc.id for loc in
        db.query(Location).filter(Location.location_type.in_(["staging", "yard"])).all()
    }
    if not staging_ids:
        return {"assigned": 0, "cars_updated": [car_to_dict(c) for c in cars]}

    assigned = 0
    for car in cars:
        assigned += auto_assign_one_car(car, unassigned, staging_ids, db)

    db.commit()
    for car in cars:
        db.refresh(car)
    return {"assigned": assigned, "cars_updated": [car_to_dict(c) for c in cars]}


@router.post("/cars/{car_id}/auto-assign")
def auto_assign_single_car(car_id: int, db: Session = Depends(get_db)):
    car = db.get(Car, car_id)
    if not car:
        raise HTTPException(404, "Car not found")
    clear_car_slots(car, db)
    db.refresh(car)
    staging_ids = {
        loc.id for loc in
        db.query(Location).filter(Location.location_type.in_(["staging", "yard"])).all()
    }
    unassigned = db.query(Waybill).filter(Waybill.car_id.is_(None)).all()
    assigned = auto_assign_one_car(car, unassigned, staging_ids, db, starting_loc=car.current_location_id)
    db.commit()
    db.refresh(car)
    return {"assigned": assigned, "car": car_to_dict(car)}
