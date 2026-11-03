# SPDX-FileCopyrightText: 2026 David Dalzell
# SPDX-License-Identifier: MIT

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session
from starlette.requests import Request

from auth import require_admin
from database import get_db
from models import Car, Location, MovementLog, Track, Waybill
from converters import location_group_to_dict, track_to_dict
from schemas import LocationCreate, MoveRequest, TrackCreate

router = APIRouter(prefix="/api", tags=["locations"])


# ── Tracks (/api/tracks) ─────────────────────────────────────────────────────

@router.get("/tracks")
def list_tracks(db: Session = Depends(get_db)):
    tracks = db.query(Track).order_by(
        func.coalesce(Track.position, Track.id), Track.id
    ).all()
    return [track_to_dict(t) for t in tracks]


@router.post("/tracks", status_code=201)
def create_track(data: TrackCreate, db: Session = Depends(get_db), _: dict = Depends(require_admin)):
    track = Track(
        name=data.name,
        location_type=data.location_type,
        location_id=data.location_id,
        car_capacity=data.car_capacity,
    )
    db.add(track)
    db.flush()
    track.position = track.id  # new tracks append to the end of their Location
    db.commit()
    db.refresh(track)
    return track_to_dict(track)


@router.post("/tracks/{track_id}/move")
def move_track(track_id: int, data: MoveRequest, db: Session = Depends(get_db), _: dict = Depends(require_admin)):
    track = db.get(Track, track_id)
    if not track:
        raise HTTPException(404, "Track not found")
    siblings = db.query(Track).filter(
        Track.location_id == track.location_id
    ).order_by(func.coalesce(Track.position, Track.id), Track.id).all()
    idx = next(i for i, s in enumerate(siblings) if s.id == track_id)
    swap = idx - 1 if data.direction == "up" else idx + 1
    if 0 <= swap < len(siblings):
        siblings[idx], siblings[swap] = siblings[swap], siblings[idx]
    for i, s in enumerate(siblings):  # normalise positions so NULLs are resolved
        s.position = i
    db.commit()
    return {"ok": True}


@router.put("/tracks/{track_id}")
def update_track(track_id: int, data: TrackCreate, db: Session = Depends(get_db), _: dict = Depends(require_admin)):
    track = db.get(Track, track_id)
    if not track:
        raise HTTPException(404, "Track not found")
    track.name = data.name
    track.location_type = data.location_type
    track.location_id = data.location_id
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


# ── Locations (/api/locations) ────────────────────────────────────────────────

@router.get("/locations")
def list_locations(db: Session = Depends(get_db)):
    areas = db.query(Location).order_by(
        func.coalesce(Location.position, Location.id), Location.id
    ).all()
    return [location_group_to_dict(a, db) for a in areas]


@router.post("/locations", status_code=201)
def create_location(data: LocationCreate, db: Session = Depends(get_db), _: dict = Depends(require_admin)):
    area = Location(name=data.name, car_capacity=data.car_capacity)
    db.add(area)
    db.flush()
    area.position = area.id  # new locations append to the end
    db.commit()
    db.refresh(area)
    return location_group_to_dict(area, db)


@router.post("/locations/{area_id}/move")
def move_location(area_id: int, data: MoveRequest, db: Session = Depends(get_db), _: dict = Depends(require_admin)):
    area = db.get(Location, area_id)
    if not area:
        raise HTTPException(404, "Location not found")
    siblings = db.query(Location).order_by(
        func.coalesce(Location.position, Location.id), Location.id
    ).all()
    idx = next(i for i, s in enumerate(siblings) if s.id == area_id)
    swap = idx - 1 if data.direction == "up" else idx + 1
    if 0 <= swap < len(siblings):
        siblings[idx], siblings[swap] = siblings[swap], siblings[idx]
    for i, s in enumerate(siblings):  # normalise positions so NULLs are resolved
        s.position = i
    db.commit()
    return {"ok": True}


@router.put("/locations/{area_id}")
def update_location(area_id: int, data: LocationCreate, db: Session = Depends(get_db), _: dict = Depends(require_admin)):
    area = db.get(Location, area_id)
    if not area:
        raise HTTPException(404, "Location not found")
    area.name = data.name
    area.car_capacity = data.car_capacity
    db.commit()
    return location_group_to_dict(area, db)


@router.delete("/locations/{area_id}", status_code=204)
def delete_location(request: Request, area_id: int, db: Session = Depends(get_db), _: dict = Depends(require_admin)):
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
