import io
import os
import uuid
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from PIL import Image
from sqlalchemy.orm import Session

import storage
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
async def upload_car_photo(file: UploadFile = File(...), skip_analysis: bool = False):
    raw_bytes = await file.read()
    # Convert to JPEG in-memory
    try:
        buf = io.BytesIO()
        with Image.open(io.BytesIO(raw_bytes)) as img:
            img.convert("RGB").save(buf, "JPEG", quality=85)
        jpeg_bytes = buf.getvalue()
    except Exception:
        jpeg_bytes = raw_bytes  # fall back to original if conversion fails

    filename = f"{uuid.uuid4().hex}.jpg"
    photo_path = storage.upload(filename, jpeg_bytes, "image/jpeg")

    if skip_analysis:
        return {"photo_path": photo_path, "car_type": "", "color": "", "car_number": "", "reporting_marks": ""}

    try:
        provider = get_provider()
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
                analysis = analyze_car_photo(str(tmp))
                tmp.unlink(missing_ok=True)
            else:
                analysis = analyze_car_photo(photo_path)
        except Exception as e:
            analysis = {"car_type": "other", "color": "", "car_number": "", "reporting_marks": ""}
            analysis["_error"] = str(e)

    analysis["photo_path"] = photo_path
    return analysis


@router.post("/cars/analyze-photo")
def analyze_existing_photo(data: AnalyzePhotoRequest):
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
    try:
        analysis = analyze_car_photo(local_path)
    except Exception as e:
        analysis = {"car_type": "other", "color": "", "car_number": "", "reporting_marks": ""}
        analysis["_error"] = str(e)
    finally:
        if tmp:
            tmp.unlink(missing_ok=True)
    analysis["photo_path"] = photo_path
    return analysis


@router.post("/cars/stylize")
def stylize_car_photo(data: StylizeRequest):
    from google import genai
    from google.genai import types

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise HTTPException(400, "GEMINI_API_KEY is not configured")

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
        raise HTTPException(500, str(e))

    filename = f"{uuid.uuid4().hex}_stylized.png"
    stylized_path = storage.upload(filename, img_bytes, "image/png")
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
def delete_car(car_id: int, db: Session = Depends(get_db)):
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
def update_car_location(car_id: int, body: dict, db: Session = Depends(get_db)):
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
