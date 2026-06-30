# SPDX-FileCopyrightText: 2026 David Dalzell
# SPDX-License-Identifier: AGPL-3.0-or-later

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from starlette.requests import Request

from database import get_db
from models import CommodityCarTypeMap
from converters import commodity_map_to_dict
from schemas import CommodityCarTypeMapCreate, CommodityCarTypeMapUpdate, CommoditySuggestRequest
from vision import get_provider

router = APIRouter(prefix="/api", tags=["commodity_map"])

_DEFAULT_COMMODITY_MAP = [
    ("lumber", "flatcar"), ("logs", "flatcar"), ("steel coils", "flatcar"), ("pipe", "flatcar"),
    ("grain", "covered hopper"), ("wheat", "covered hopper"), ("corn", "covered hopper"), ("flour", "covered hopper"),
    ("coal", "hopper"), ("gravel", "hopper"), ("sand", "hopper"), ("ballast", "hopper"),
    ("fuel oil", "tank car"), ("crude oil", "tank car"), ("chemicals", "tank car"), ("gasoline", "tank car"),
    ("produce", "refrigerator car"), ("meat", "refrigerator car"), ("frozen goods", "refrigerator car"),
    ("merchandise", "boxcar"), ("auto parts", "boxcar"), ("paper", "boxcar"), ("canned goods", "boxcar"),
    ("steel", "gondola"), ("scrap metal", "gondola"), ("machinery", "gondola"),
]


@router.get("/commodity-car-type-map")
def list_commodity_map(db: Session = Depends(get_db)):
    rows = db.query(CommodityCarTypeMap).order_by(CommodityCarTypeMap.commodity).all()
    return [commodity_map_to_dict(r) for r in rows]


@router.post("/commodity-car-type-map/seed", status_code=201)
def seed_commodity_map(db: Session = Depends(get_db)):
    added = skipped = 0
    for commodity, car_type in _DEFAULT_COMMODITY_MAP:
        if db.query(CommodityCarTypeMap).filter_by(commodity=commodity).first():
            skipped += 1
        else:
            db.add(CommodityCarTypeMap(commodity=commodity, car_type=car_type))
            added += 1
    db.commit()
    return {"added": added, "skipped": skipped}


@router.post("/commodity-car-type-map/suggest")
def suggest_commodity_endpoint(request: Request, data: CommoditySuggestRequest, db: Session = Depends(get_db)):
    tenant = getattr(request.state, "tenant", None)
    if not get_provider(tenant).is_available():
        raise HTTPException(503, "No AI provider available — check your API key settings")
    existing = {r.commodity: r.car_type for r in db.query(CommodityCarTypeMap).all()}
    try:
        from vision import suggest_commodity_car_type
        result = suggest_commodity_car_type(data.commodity, existing, tenant)
    except Exception as e:
        raise HTTPException(500, str(e))
    return {"car_type": result.get("car_type", "boxcar")}


@router.post("/commodity-car-type-map", status_code=201)
def create_commodity_map(data: CommodityCarTypeMapCreate, db: Session = Depends(get_db)):
    normalized = data.commodity.strip().lower()
    if not normalized:
        raise HTTPException(400, "Commodity name cannot be empty")
    if db.query(CommodityCarTypeMap).filter_by(commodity=normalized).first():
        raise HTTPException(409, f"Mapping for '{normalized}' already exists")
    entry = CommodityCarTypeMap(commodity=normalized, car_type=data.car_type.strip().lower())
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return commodity_map_to_dict(entry)


@router.put("/commodity-car-type-map/{map_id}")
def update_commodity_map(map_id: int, data: CommodityCarTypeMapUpdate, db: Session = Depends(get_db)):
    entry = db.get(CommodityCarTypeMap, map_id)
    if not entry:
        raise HTTPException(404, "Mapping not found")
    entry.car_type = data.car_type.strip().lower()
    db.commit()
    db.refresh(entry)
    return commodity_map_to_dict(entry)


@router.delete("/commodity-car-type-map/{map_id}", status_code=204)
def delete_commodity_map(map_id: int, db: Session = Depends(get_db)):
    entry = db.get(CommodityCarTypeMap, map_id)
    if not entry:
        raise HTTPException(404, "Mapping not found")
    db.delete(entry)
    db.commit()
