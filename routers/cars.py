# SPDX-FileCopyrightText: 2026 David Dalzell
# SPDX-License-Identifier: MIT

import io
import os
import uuid
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from PIL import Image
from sqlalchemy.orm import Session
from starlette.requests import Request

import storage
from auth import get_current_user
from database import get_db
from models import Car, Location, MovementLog, Waybill
from converters import car_to_dict, waybill_to_dict
from schemas import AnalyzePhotoRequest, CarCreate, CarSlotsUpdate, CarUpdate, StylizeRequest
from vision import analyze_car_photo, call_with_retry, get_provider

_PROMPTS_DIR = Path("prompts")


def _load_stylize_config() -> dict:
    p = _PROMPTS_DIR / "stylize_car.json"
    try:
        import json
        return json.loads(p.read_text(encoding="utf-8"))
    except (FileNotFoundError, __import__("json").JSONDecodeError):
        return {}


_stylize_cfg = _load_stylize_config()
STYLIZE_PROMPT = _stylize_cfg.get(
    "prompt",
    "Illustration of the side view of a railway car based on the reference image. "
    "The image should be on a background of color #FAF0E6 and look like a simplified "
    "blueprint without dimensional lines. The lines are antialiased. The railway car "
    "body should be tinted with a single color that matches the image. The wheels and "
    "trucks should be tinted a brownish color. Tints should be around 30% darkness",
)
STYLIZE_MODEL = _stylize_cfg.get("model", "gemini-3.1-flash-image")

router = APIRouter(prefix="/api", tags=["cars"])


@router.get("/cars")
def list_cars(db: Session = Depends(get_db)):
    cars = db.query(Car).all()
    return [car_to_dict(c) for c in cars]


@router.post("/cars/repair")
def repair_orphaned_cars(db: Session = Depends(get_db)):
    valid_ids = {row.id for row in db.query(Location.id).all()}
    orphaned = db.query(Car).filter(
        Car.current_location_id.isnot(None),
        Car.current_location_id.notin_(valid_ids)
    ).all()
    count = len(orphaned)
    for car in orphaned:
        car.current_location_id = None
    db.commit()
    return {"repaired": count}


@router.post("/cars/upload")
async def upload_car_photo(request: Request, file: UploadFile = File(...), skip_analysis: bool = False):
    raw_bytes = await file.read()
    # Convert to JPEG in-memory
    try:
        buf = io.BytesIO()
        with Image.open(io.BytesIO(raw_bytes)) as img:
            img.convert("RGB").save(buf, "JPEG", quality=85)
        jpeg_bytes = buf.getvalue()
    except Exception:
        jpeg_bytes = raw_bytes  # fall back to original if conversion fails

    tenant = getattr(request.state, "tenant", None)
    folder = getattr(tenant, "schema_name", None) or "uploads"
    filename = f"{uuid.uuid4().hex}.jpg"
    photo_path = storage.upload(filename, jpeg_bytes, "image/jpeg", folder=folder)

    if skip_analysis:
        return {"photo_path": photo_path, "car_type": "", "color": "", "car_number": "", "reporting_marks": ""}

    from auth import is_demo
    import demo_limits
    if is_demo(request) and not demo_limits.check_and_increment("analysis"):
        analysis = {"car_type": "other", "color": "", "car_number": "", "reporting_marks": ""}
        analysis["photo_path"] = photo_path
        analysis["_error"] = "Demo analysis limit reached (10/hr) — subscribe to use AI features on your own layout."
        return analysis

    try:
        provider = get_provider(tenant)
    except ValueError:
        provider = None

    if not provider or not provider.is_available():
        analysis = {"car_type": "other", "color": "", "car_number": "", "reporting_marks": ""}
    else:
        try:
            # analyze_car_photo accepts a path or URL-like string; for Supabase URLs
            # we write a temp file since the vision module expects a filesystem path
            if photo_path.startswith("http"):
                tmp = Path(f"/tmp/{filename}")
                tmp.write_bytes(jpeg_bytes)
                analysis = analyze_car_photo(str(tmp), tenant)
                tmp.unlink(missing_ok=True)
            else:
                analysis = analyze_car_photo(photo_path, tenant)
        except Exception as e:
            analysis = {"car_type": "other", "color": "", "car_number": "", "reporting_marks": ""}
            analysis["_error"] = str(e)

    analysis["photo_path"] = photo_path
    return analysis


@router.post("/cars/analyze-photo")
def analyze_existing_photo(request: Request, data: AnalyzePhotoRequest):
    from auth import is_demo
    import demo_limits
    if is_demo(request) and not demo_limits.check_and_increment("analysis"):
        raise HTTPException(429, "Demo analysis limit reached (10/hr) — subscribe to use AI features on your own layout.")
    photo_path = data.photo_path
    if photo_path.startswith("http"):
        # Supabase CDN URL — download to a temp file for analysis
        try:
            raw = storage.read_bytes(photo_path)
        except Exception:
            raise HTTPException(404, "Photo not found")
        tmp = Path(f"/tmp/{uuid.uuid4().hex}.jpg")
        tmp.write_bytes(raw)
        local_path = str(tmp)
    else:
        if not Path(photo_path).exists():
            raise HTTPException(404, "Photo not found")
        local_path = photo_path
        tmp = None
    tenant = getattr(request.state, "tenant", None)
    try:
        analysis = analyze_car_photo(local_path, tenant)
    except Exception as e:
        analysis = {"car_type": "other", "color": "", "car_number": "", "reporting_marks": ""}
        analysis["_error"] = str(e)
    finally:
        if tmp:
            tmp.unlink(missing_ok=True)
    analysis["photo_path"] = photo_path
    return analysis


@router.post("/cars/stylize")
def stylize_car_photo(request: Request, data: StylizeRequest):
    from auth import is_demo
    import demo_limits
    if is_demo(request) and not demo_limits.check_and_increment("stylize"):
        raise HTTPException(429, "Demo stylize limit reached (5/hr) — subscribe to use AI features on your own layout.")
    from google import genai
    from google.genai import types

    tenant = getattr(request.state, "tenant", None)
    api_key = (getattr(tenant, "gemini_api_key", None) if tenant else None) or os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise HTTPException(400, "No Gemini API key configured")

    photo_path = data.photo_path
    if photo_path.startswith("http"):
        try:
            image_bytes = storage.read_bytes(photo_path)
        except Exception:
            raise HTTPException(404, "Source photo not found")
    else:
        src = Path(photo_path)
        if not src.exists():
            raise HTTPException(404, "Source photo not found")
        image_bytes = src.read_bytes()

    try:
        client = genai.Client(api_key=api_key)
        response = call_with_retry(lambda: client.models.generate_content(
            model=STYLIZE_MODEL,
            contents=[
                types.Part.from_bytes(data=image_bytes, mime_type="image/jpeg"),
                STYLIZE_PROMPT,
            ],
            config=types.GenerateContentConfig(
                response_modalities=["IMAGE", "TEXT"],
            ),
        ))

        img_bytes = None
        for part in response.candidates[0].content.parts:
            if part.inline_data:
                img_bytes = part.inline_data.data
                break

        if not img_bytes:
            raise HTTPException(500, "Gemini did not return an image")

    except HTTPException:
        raise
    except Exception as e:
        try:
            from google.genai.errors import ClientError as _GErr
            if isinstance(e, _GErr):
                code = getattr(e, "code", 0) or 0
                status = str(getattr(e, "status", "") or "").upper()
                msg = str(e).lower()
                if code in (403, 429) and (
                    "RESOURCE_EXHAUSTED" in status or "quota" in msg or "billing" in msg
                ):
                    raise HTTPException(
                        402,
                        "Image generation is not available with the free Gemini API tier"
                        " — a paid key is required.",
                    )
        except HTTPException:
            raise
        except Exception:
            pass
        raise HTTPException(500, str(e))

    filename = f"{uuid.uuid4().hex}_stylized.png"
    tenant = getattr(request.state, "tenant", None)
    folder = getattr(tenant, "schema_name", None) or "uploads"
    stylized_path = storage.upload(filename, img_bytes, "image/png", folder=folder)
    return {"stylized_path": stylized_path, "url": storage.photo_url(stylized_path)}


@router.post("/cars", status_code=201)
def create_car(data: CarCreate, db: Session = Depends(get_db)):
    car = Car(**data.model_dump())
    db.add(car)
    db.commit()
    db.refresh(car)
    return car_to_dict(car)


@router.put("/cars/{car_id}")
def update_car(car_id: int, data: CarUpdate, db: Session = Depends(get_db)):
    car = db.get(Car, car_id)
    if not car:
        raise HTTPException(404, "Car not found")
    updates = data.model_dump(exclude_none=True)
    new_path = updates.get("photo_path")
    if new_path and new_path != car.photo_path and car.photo_path:
        storage.delete(car.photo_path)
    for field, value in updates.items():
        setattr(car, field, value)
    db.commit()
    db.refresh(car)
    return car_to_dict(car)


@router.delete("/cars/{car_id}", status_code=204)
def delete_car(request: Request, car_id: int, db: Session = Depends(get_db)):
    from auth import is_demo
    if is_demo(request):
        raise HTTPException(403, "Deleting cars is disabled in the demo")
    car = db.get(Car, car_id)
    if not car:
        raise HTTPException(404, "Car not found")
    for w in car.waybills:
        w.car_id = None
        w.slot_index = None
    db.query(MovementLog).filter(MovementLog.car_id == car_id).delete(synchronize_session=False)
    storage.delete(car.photo_path)
    db.delete(car)
    db.commit()


@router.post("/cars/{car_id}/advance")
def advance_waybill(car_id: int, db: Session = Depends(get_db)):
    car = db.get(Car, car_id)
    if not car:
        raise HTTPException(404, "Car not found")
    assigned = sorted(w.slot_index for w in car.waybills if w.slot_index is not None)
    if assigned:
        try:
            idx = assigned.index(car.active_waybill_slot)
            car.active_waybill_slot = assigned[(idx + 1) % len(assigned)]
        except ValueError:
            car.active_waybill_slot = assigned[0]
    db.commit()
    db.refresh(car)
    return car_to_dict(car)


@router.put("/cars/{car_id}/location")
def update_car_location(car_id: int, body: dict, db: Session = Depends(get_db),
                        user: dict = Depends(get_current_user)):
    car = db.get(Car, car_id)
    if not car:
        raise HTTPException(404, "Car not found")

    new_loc_id = body.get("location_id")
    old_loc_id = car.current_location_id

    log = MovementLog(
        car_id=car_id,
        from_location_id=old_loc_id,
        to_location_id=new_loc_id,
        note=body.get("note", ""),
        operator_email=(user or {}).get("email", "local"),
    )
    db.add(log)
    car.current_location_id = new_loc_id
    db.commit()
    db.refresh(car)
    return car_to_dict(car)


@router.get("/cars/{car_id}/waybills")
def get_car_waybills(car_id: int, db: Session = Depends(get_db)):
    car = db.get(Car, car_id)
    if not car:
        raise HTTPException(404, "Car not found")
    return [waybill_to_dict(w) for w in car.waybills]


@router.put("/cars/{car_id}/slots")
def assign_slots(car_id: int, data: CarSlotsUpdate, db: Session = Depends(get_db)):
    car = db.get(Car, car_id)
    if not car:
        raise HTTPException(404, "Car not found")

    for assignment in data.slots:
        # Clear any waybill already in this slot on this car
        existing = (
            db.query(Waybill)
            .filter(Waybill.car_id == car_id, Waybill.slot_index == assignment.slot_index)
            .first()
        )
        if existing:
            existing.car_id = None
            existing.slot_index = None

        if assignment.waybill_id:
            w = db.get(Waybill, assignment.waybill_id)
            if w:
                # Unassign it from wherever it currently is
                if w.car_id and w.car_id != car_id:
                    w.car_id = None
                    w.slot_index = None
                w.car_id = car_id
                w.slot_index = assignment.slot_index

    db.commit()
    db.refresh(car)
    return [waybill_to_dict(w) for w in car.waybills]
