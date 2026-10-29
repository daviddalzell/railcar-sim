# SPDX-FileCopyrightText: 2026 David Dalzell
# SPDX-License-Identifier: MIT

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from starlette.requests import Request

from auth import require_admin
from database import get_db
from models import Car, Location, MovementLog, Track, Waybill
from converters import location_group_to_dict, track_to_dict
from schemas import LocationCreate, TrackCreate

router = APIRouter(prefix="/api", tags=["locations"])


# ── Tracks (/api/tracks — primary new path) ───────────────────────────────────

@router.get("/tracks")
def list_tracks(db: Session = Depends(get_db)):
    return [track_to_dict(t) for t in db.query(Track).all()]


@router.post("/tracks", status_code=201)
def create_track(data: TrackCreate, db: Session = Depends(get_db), _: dict = Depends(require_admin)):
    track = Track(
        name=data.name,
        location_type=data.location_type,
        location_id=data.switching_area_id,
        car_capacity=data.car_capacity,
    )
    db.add(track)
    db.commit()
    db.refresh(track)
    return track_to_dict(track)


@router.put("/tracks/{track_id}")
def update_track(track_id: int, data: TrackCreate, db: Session = Depends(get_db), _: dict = Depends(require_admin)):
    track = db.get(Track, track_id)
    if not track:
        raise HTTPException(404, "Track not found")
    track.name = data.name
    track.location_type = data.location_type
    track.location_id = data.switching_area_id
    track.car_capacity = data.car_capacity
    db.commit()
    return track_to_dict(track)


@router.delete("/tracks/{track_id}")
def delete_track(request: Request, track_id: int, merge_into_id: Optional[int] = None, db: Session = Depends(get_db), _: dict = Depends(require_admin)):
    from auth import is_demo
    if is_demo(request):
        raise HTTPException(403, "Deleting tracks is disabled in the demo")
    track = db.get(Track, track_id)
    if not track:
        raise HTTPException(404, "Track not found")

    if track.location_type == "staging":
        if merge_into_id is None:
            raise HTTPException(400, "Staging tracks require a merge target")
        target = db.get(Track, merge_into_id)
        if not target or target.location_type != "staging":
            raise HTTPException(400, "Merge target must be a staging track")
        db.query(Car).filter(Car.current_location_id == track_id).update({"current_location_id": merge_into_id})
        db.query(Waybill).filter(Waybill.origin_id == track_id).update({"origin_id": merge_into_id})
        db.query(Waybill).filter(Waybill.destination_id == track_id).update({"destination_id": merge_into_id})
        db.query(MovementLog).filter(MovementLog.from_location_id == track_id).update({"from_location_id": merge_into_id})
        db.query(MovementLog).filter(MovementLog.to_location_id == track_id).update({"to_location_id": merge_into_id})
        db.flush()
        db.delete(track)
        db.commit()
        return {"action": "merged", "into": target.name}

    else:
        blocking = db.query(Car).filter(Car.current_location_id == track_id).all()
        if blocking:
            raise HTTPException(409, detail={
                "message": f"Cars must be moved before deleting \"{track.name}\"",
                "cars": [{"id": c.id, "reporting_marks": c.reporting_marks,
                           "car_number": c.car_number, "car_type": c.car_type} for c in blocking]
            })
        db.query(MovementLog).filter(MovementLog.from_location_id == track_id).update({"from_location_id": None})
        db.query(MovementLog).filter(MovementLog.to_location_id == track_id).update({"to_location_id": None})
        db.query(Waybill).filter(
            (Waybill.origin_id == track_id) | (Waybill.destination_id == track_id)
        ).delete(synchronize_session=False)
        db.delete(track)
        db.commit()
        return {"action": "deleted"}


# ── Backward-compat aliases: /api/locations → Track CRUD (old frontend uses this path) ───

@router.get("/locations")
def list_locations_alias(db: Session = Depends(get_db)):
    return list_tracks(db)


@router.post("/locations", status_code=201)
def create_location_alias(data: TrackCreate, db: Session = Depends(get_db), _: dict = Depends(require_admin)):
    return create_track(data, db, _)


@router.put("/locations/{track_id}")
def update_location_alias(track_id: int, data: TrackCreate, db: Session = Depends(get_db), _: dict = Depends(require_admin)):
    return update_track(track_id, data, db, _)


@router.delete("/locations/{track_id}")
def delete_location_alias(request: Request, track_id: int, merge_into_id: Optional[int] = None, db: Session = Depends(get_db), _: dict = Depends(require_admin)):
    return delete_track(request, track_id, merge_into_id, db, _)


# ── Locations (/api/switching-areas — old path, kept for compat) ──────────────

@router.get("/switching-areas")
def list_switching_areas(db: Session = Depends(get_db)):
    areas = db.query(Location).all()
    return [location_group_to_dict(a, db) for a in areas]


@router.post("/switching-areas", status_code=201)
def create_switching_area(data: LocationCreate, db: Session = Depends(get_db), _: dict = Depends(require_admin)):
    area = Location(name=data.name, car_capacity=data.car_capacity)
    db.add(area)
    db.commit()
    db.refresh(area)
    return location_group_to_dict(area, db)


@router.put("/switching-areas/{area_id}")
def update_switching_area(area_id: int, data: LocationCreate, db: Session = Depends(get_db), _: dict = Depends(require_admin)):
    area = db.get(Location, area_id)
    if not area:
        raise HTTPException(404, "Location not found")
    area.name = data.name
    area.car_capacity = data.car_capacity
    db.commit()
    return location_group_to_dict(area, db)


@router.delete("/switching-areas/{area_id}", status_code=204)
def delete_switching_area(request: Request, area_id: int, db: Session = Depends(get_db), _: dict = Depends(require_admin)):
    from auth import is_demo
    if is_demo(request):
        raise HTTPException(403, "Deleting locations is disabled in the demo")
    area = db.get(Location, area_id)
    if not area:
        raise HTTPException(404, "Location not found")
    db.query(Track).filter(Track.location_id == area_id).update(
        {"location_id": None}, synchronize_session=False
    )
    db.delete(area)
    db.commit()
