# SPDX-FileCopyrightText: 2026 David Dalzell
# SPDX-License-Identifier: AGPL-3.0-or-later

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from database import get_db
from models import Car, CarType
from schemas import CarTypeCreate

router = APIRouter(prefix="/api", tags=["car_types"])


@router.get("/car-types")
def list_car_types(db: Session = Depends(get_db)):
    return [{"id": ct.id, "name": ct.name, "default_photo_path": ct.default_photo_path} for ct in db.query(CarType).order_by(CarType.name).all()]


@router.post("/car-types", status_code=201)
def create_car_type(data: CarTypeCreate, db: Session = Depends(get_db)):
    name = data.name.strip().lower()
    if not name:
        raise HTTPException(400, "Name is required")
    if db.query(CarType).filter(CarType.name == name).first():
        raise HTTPException(409, "Car type already exists")
    ct = CarType(name=name)
    db.add(ct)
    db.commit()
    db.refresh(ct)
    return {"id": ct.id, "name": ct.name}


@router.put("/car-types/{ct_id}/default-image")
def set_car_type_default_image(ct_id: int, body: dict, db: Session = Depends(get_db)):
    ct = db.get(CarType, ct_id)
    if not ct:
        raise HTTPException(404)
    ct.default_photo_path = body.get("photo_path") or None
    db.commit()
    return {"ok": True}


@router.delete("/car-types/{ct_id}", status_code=204)
def delete_car_type(ct_id: int, db: Session = Depends(get_db)):
    ct = db.get(CarType, ct_id)
    if not ct:
        raise HTTPException(404)
    if db.query(Car).filter(Car.car_type == ct.name).first():
        raise HTTPException(409, f'Cars exist with type "{ct.name}" — reassign them first')
    db.delete(ct)
    db.commit()
