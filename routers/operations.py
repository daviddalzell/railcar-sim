# SPDX-FileCopyrightText: 2026 David Dalzell
# SPDX-License-Identifier: AGPL-3.0-or-later

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from database import get_db
from models import Car, MovementLog, SwitchingArea, Location
from converters import car_to_dict, switching_area_to_dict

router = APIRouter(prefix="/api", tags=["operations"])


def _get_active_waybill(car: Car):
    return next((w for w in car.waybills if w.slot_index == car.active_waybill_slot), None)


def _enrich_car_for_status(car: Car) -> dict:
    wb = _get_active_waybill(car)
    return {
        "id": car.id,
        "reporting_marks": car.reporting_marks,
        "car_number": car.car_number,
        "car_type": car.car_type,
        "destination_name": wb.destination.name if wb and wb.destination else None,
    }


@router.get("/layout-status")
def layout_status(db: Session = Depends(get_db)):
    areas = db.query(SwitchingArea).all()
    area_dicts = []
    for area in areas:
        d = switching_area_to_dict(area, db)
        loc_ids = [l.id for l in area.locations]
        cars = db.query(Car).filter(Car.current_location_id.in_(loc_ids)).all() if loc_ids else []
        d["cars"] = [_enrich_car_for_status(c) for c in cars]
        area_dicts.append(d)

    yard_locs = db.query(Location).filter(
        Location.location_type.in_(["staging", "yard"])
    ).all()
    yard_dicts = []
    for loc in yard_locs:
        cars = db.query(Car).filter(Car.current_location_id == loc.id).all()
        yard_dicts.append({
            "id": loc.id,
            "name": loc.name,
            "location_type": loc.location_type,
            "car_count": len(cars),
            "cars": [_enrich_car_for_status(c) for c in cars],
        })

    return {"switching_areas": area_dicts, "yards": yard_dicts}


@router.get("/operations")
def operations(db: Session = Depends(get_db)):
    cars = db.query(Car).all()
    result = []
    for car in cars:
        d = car_to_dict(car)
        logs = (
            db.query(MovementLog)
            .filter(MovementLog.car_id == car.id)
            .order_by(MovementLog.timestamp.desc())
            .limit(5)
            .all()
        )
        d["recent_moves"] = [
            {
                "timestamp": log.timestamp.isoformat(),
                "from_location_id": log.from_location_id,
                "to_location_id": log.to_location_id,
                "note": log.note,
            }
            for log in logs
        ]
        result.append(d)
    return result
