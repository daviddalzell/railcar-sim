# SPDX-FileCopyrightText: 2026 David Dalzell
# SPDX-License-Identifier: AGPL-3.0-or-later

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from database import get_db
from models import Waybill
from converters import waybill_to_dict
from schemas import WaybillCreate

router = APIRouter(prefix="/api", tags=["waybills"])


@router.get("/waybills")
def list_waybills(db: Session = Depends(get_db)):
    return [waybill_to_dict(w) for w in db.query(Waybill).all()]


@router.post("/waybills", status_code=201)
def create_waybill(data: WaybillCreate, db: Session = Depends(get_db)):
    w = Waybill(**data.model_dump())
    db.add(w)
    db.commit()
    db.refresh(w)
    return waybill_to_dict(w)


@router.put("/waybills/{waybill_id}")
def update_waybill(waybill_id: int, data: WaybillCreate, db: Session = Depends(get_db)):
    w = db.get(Waybill, waybill_id)
    if not w:
        raise HTTPException(404, "Waybill not found")
    for field, value in data.model_dump().items():
        setattr(w, field, value)
    db.commit()
    db.refresh(w)
    return waybill_to_dict(w)


@router.delete("/waybills/{waybill_id}", status_code=204)
def delete_waybill(waybill_id: int, db: Session = Depends(get_db)):
    w = db.get(Waybill, waybill_id)
    if not w:
        raise HTTPException(404, "Waybill not found")
    db.delete(w)
    db.commit()
