# SPDX-FileCopyrightText: 2026 David Dalzell
# SPDX-License-Identifier: MIT

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from database import get_db
from models import Car, Location, MovementLog, Track
from converters import car_to_dict, location_group_to_dict

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
    areas = db.query(Location).all()
    area_dicts = []
    for area in areas:
        d = location_group_to_dict(area, db)
        track_ids = [t.id for t in area.tracks]
        cars = db.query(Car).filter(Car.current_location_id.in_(track_ids)).all() if track_ids else []
        d["cars"] = [_enrich_car_for_status(c) for c in cars]
        area_dicts.append(d)

    yard_tracks = db.query(Track).filter(
        Track.location_type.in_(["staging", "yard"])
    ).all()
    yard_dicts = []
    for track in yard_tracks:
        cars = db.query(Car).filter(Car.current_location_id == track.id).all()
        yard_dicts.append({
            "id": track.id,
            "name": track.name,
            "location_type": track.location_type,
            "car_count": len(cars),
            "cars": [_enrich_car_for_status(c) for c in cars],
        })

    # "switching_areas" key kept for old-frontend backward compat
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
