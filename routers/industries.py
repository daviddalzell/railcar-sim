# SPDX-FileCopyrightText: 2026 David Dalzell
# SPDX-License-Identifier: MIT

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from starlette.requests import Request

from database import get_db
from models import CommodityCarTypeMap, Industry, Waybill
from converters import industry_to_dict
from schemas import IndustryCreate, IndustrySuggestRequest
from vision import get_provider

router = APIRouter(prefix="/api", tags=["industries"])


@router.get("/industries")
def list_industries(db: Session = Depends(get_db)):
    return [industry_to_dict(i) for i in db.query(Industry).all()]


@router.post("/industries", status_code=201)
def create_industry(data: IndustryCreate, db: Session = Depends(get_db)):
    ind = Industry(**data.model_dump())
    db.add(ind)
    db.commit()
    db.refresh(ind)
    return industry_to_dict(ind)


@router.put("/industries/{ind_id}")
def update_industry(ind_id: int, data: IndustryCreate, db: Session = Depends(get_db)):
    ind = db.get(Industry, ind_id)
    if not ind:
        raise HTTPException(404, "Industry not found")
    for field, value in data.model_dump().items():
        setattr(ind, field, value)
    db.commit()
    return industry_to_dict(ind)


@router.delete("/industries/{ind_id}", status_code=204)
def delete_industry(request: Request, ind_id: int, db: Session = Depends(get_db)):
    from auth import is_demo
    if is_demo(request):
        raise HTTPException(403, "Deleting industries is disabled in the demo")
    ind = db.get(Industry, ind_id)
    if not ind:
        raise HTTPException(404, "Industry not found")
    db.query(Waybill).filter(Waybill.industry_id == ind_id, Waybill.car_id == None).delete(synchronize_session=False)
    db.delete(ind)
    db.commit()


@router.post("/industries/suggest")
def suggest_industry_endpoint(request: Request, data: IndustrySuggestRequest, db: Session = Depends(get_db)):
    tenant = getattr(request.state, "tenant", None)
    if not get_provider(tenant).is_available():
        raise HTTPException(503, "No AI provider available — check your API key settings")
    existing = [r.name for r in db.query(Industry).all()]
    known_commodities = [r.commodity for r in db.query(CommodityCarTypeMap).all()]
    try:
        from vision import suggest_industry
        result = suggest_industry(data.description, existing, known_commodities, tenant)
    except Exception as e:
        raise HTTPException(500, str(e))
    return {
        "industry_role": result.get("industry_role", "consumer"),
        "inbound_commodities": result.get("inbound_commodities", result.get("commodities", "")),
        "inbound_car_types": result.get("inbound_car_types", result.get("accepted_car_types", "")),
        "outbound_commodities": result.get("outbound_commodities", ""),
        "outbound_car_types": result.get("outbound_car_types", ""),
    }
