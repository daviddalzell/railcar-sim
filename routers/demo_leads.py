# SPDX-FileCopyrightText: 2026 David Dalzell
# SPDX-License-Identifier: MIT

import re

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from starlette.requests import Request

from auth import is_demo
from database import get_db
from models import DemoLead

router = APIRouter(prefix="/api", tags=["demo_leads"])

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class DemoLeadCreate(BaseModel):
    email: str
    marketing_opt_in: bool = False


@router.post("/demo-leads", status_code=204)
def capture_demo_lead(request: Request, data: DemoLeadCreate, db: Session = Depends(get_db)):
    if not is_demo(request):
        raise HTTPException(403, "Not available outside the demo")
    email = data.email.strip().lower()
    if not email or not _EMAIL_RE.match(email):
        raise HTTPException(422, "Invalid email address")
    existing = db.query(DemoLead).filter_by(email=email).first()
    if existing:
        if data.marketing_opt_in and not existing.marketing_opt_in:
            existing.marketing_opt_in = True
            db.commit()
        return
    db.add(DemoLead(email=email, marketing_opt_in=data.marketing_opt_in))
    db.commit()
