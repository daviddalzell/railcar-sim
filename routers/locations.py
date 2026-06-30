# SPDX-FileCopyrightText: 2026 David Dalzell
# SPDX-License-Identifier: AGPL-3.0-or-later

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from database import get_db
from models import Car, Location, MovementLog, SwitchingArea, Waybill
from converters import location_to_dict, switching_area_to_dict
from schemas import LocationCreate, SwitchingAreaCreate

router = APIRouter(prefix="/api", tags=["locations"])


# ── Locations ─────────────────────────────────────────────────────────────────

@router.get("/locations")
def list_locations(db: Session = Depends(get_db)):
    return [location_to_dict(l) for l in db.query(Location).all()]


@router.post("/locations", status_code=201)
def create_location(data: LocationCreate, db: Session = Depends(get_db)):
    loc = Location(**data.model_dump())
    db.add(loc)
    db.commit()
    db.refresh(loc)
    return location_to_dict(loc)


@router.put("/locations/{loc_id}")
def update_location(loc_id: int, data: LocationCreate, db: Session = Depends(get_db)):
    loc = db.get(Location, loc_id)
    if not loc:
        raise HTTPException(404, "Location not found")
    loc.name = data.name
    loc.location_type = data.location_type
    loc.switching_area_id = data.switching_area_id
    loc.car_capacity = data.car_capacity
    db.commit()
    return location_to_dict(loc)


@router.delete("/locations/{loc_id}")
def delete_location(loc_id: int, merge_into_id: Optional[int] = None, db: Session = Depends(get_db)):
    loc = db.get(Location, loc_id)
    if not loc:
        raise HTTPException(404, "Location not found")

    if loc.location_type == "staging":
        if merge_into_id is None:
            raise HTTPException(400, "Staging locations require a merge target")
        target = db.get(Location, merge_into_id)
        if not target or target.location_type != "staging":
            raise HTTPException(400, "Merge target must be a staging location")
        db.query(Car).filter(Car.current_location_id == loc_id).update({"current_location_id": merge_into_id})
        db.query(Waybill).filter(Waybill.origin_id == loc_id).update({"origin_id": merge_into_id})
        db.query(Waybill).filter(Waybill.destination_id == loc_id).update({"destination_id": merge_into_id})
        db.query(MovementLog).filter(MovementLog.from_location_id == loc_id).update({"from_location_id": merge_into_id})
        db.query(MovementLog).filter(MovementLog.to_location_id == loc_id).update({"to_location_id": merge_into_id})
        db.flush()
        db.delete(loc)
        db.commit()
        return {"action": "merged", "into": target.name}

    else:
        blocking = db.query(Car).filter(Car.current_location_id == loc_id).all()
        if blocking:
            raise HTTPException(409, detail={
                "message": f"Cars must be moved before deleting \"{loc.name}\"",
                "cars": [{"id": c.id, "reporting_marks": c.reporting_marks,
                           "car_number": c.car_number, "car_type": c.car_type} for c in blocking]
            })
        db.query(MovementLog).filter(MovementLog.from_location_id == loc_id).update({"from_location_id": None})
        db.query(MovementLog).filter(MovementLog.to_location_id == loc_id).update({"to_location_id": None})
        db.query(Waybill).filter(
            (Waybill.origin_id == loc_id) | (Waybill.destination_id == loc_id)
        ).delete(synchronize_session=False)
        db.delete(loc)
        db.commit()
        return {"action": "deleted"}


# ── Switching Areas ───────────────────────────────────────────────────────────

@router.get("/switching-areas")
def list_switching_areas(db: Session = Depends(get_db)):
    areas = db.query(SwitchingArea).all()
    return [switching_area_to_dict(a, db) for a in areas]


@router.post("/switching-areas", status_code=201)
def create_switching_area(data: SwitchingAreaCreate, db: Session = Depends(get_db)):
    area = SwitchingArea(name=data.name, car_capacity=data.car_capacity)
    db.add(area)
    db.commit()
    db.refresh(area)
    return switching_area_to_dict(area, db)


@router.put("/switching-areas/{area_id}")
def update_switching_area(area_id: int, data: SwitchingAreaCreate, db: Session = Depends(get_db)):
    area = db.get(SwitchingArea, area_id)
    if not area:
        raise HTTPException(404, "Switching area not found")
    area.name = data.name
    area.car_capacity = data.car_capacity
    db.commit()
    return switching_area_to_dict(area, db)


@router.delete("/switching-areas/{area_id}", status_code=204)
def delete_switching_area(area_id: int, db: Session = Depends(get_db)):
    area = db.get(SwitchingArea, area_id)
    if not area:
        raise HTTPException(404, "Switching area not found")
    db.query(Location).filter(Location.switching_area_id == area_id).update(
        {"switching_area_id": None}, synchronize_session=False
    )
    db.delete(area)
    db.commit()
