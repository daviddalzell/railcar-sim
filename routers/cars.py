import os
import shutil
import uuid
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from PIL import Image
from sqlalchemy.orm import Session

from database import get_db
from models import Car, Location, MovementLog, Waybill
from converters import car_to_dict, waybill_to_dict
from schemas import AnalyzePhotoRequest, CarCreate, CarSlotsUpdate, CarUpdate, StylizeRequest
from vision import analyze_car_photo, call_with_retry, get_provider

UPLOADS_DIR = Path("uploads")

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
    suffix = Path(file.filename).suffix if file.filename else ".jpg"
    raw = UPLOADS_DIR / f"{uuid.uuid4().hex}{suffix}"
    with raw.open("wb") as f:
        shutil.copyfileobj(file.file, f)
    dest = raw.with_suffix(".jpg")
    try:
        with Image.open(raw) as img:
            img.convert("RGB").save(dest, "JPEG", quality=85)
        if raw != dest:
            raw.unlink(missing_ok=True)
    except Exception:
        dest = raw  # fall back to original if conversion fails

    if skip_analysis:
        return {"photo_path": str(dest), "car_type": "", "color": "", "car_number": "", "reporting_marks": ""}

    try:
        provider = get_provider()
    except ValueError:
        provider = None

    if not provider or not provider.is_available():
        analysis = {"car_type": "other", "color": "", "car_number": "", "reporting_marks": ""}
    else:
        try:
            analysis = analyze_car_photo(str(dest))
        except Exception as e:
            analysis = {"car_type": "other", "color": "", "car_number": "", "reporting_marks": ""}
            analysis["_error"] = str(e)

    analysis["photo_path"] = str(dest)
    return analysis


@router.post("/cars/analyze-photo")
def analyze_existing_photo(data: AnalyzePhotoRequest):
    if not Path(data.photo_path).exists():
        raise HTTPException(404, "Photo not found")
    try:
        analysis = analyze_car_photo(data.photo_path)
    except Exception as e:
        analysis = {"car_type": "other", "color": "", "car_number": "", "reporting_marks": ""}
        analysis["_error"] = str(e)
    analysis["photo_path"] = data.photo_path
    return analysis


@router.post("/cars/stylize")
def stylize_car_photo(data: StylizeRequest):
    from google import genai
    from google.genai import types

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise HTTPException(400, "GEMINI_API_KEY is not configured")

    src = Path(data.photo_path)
    if not src.exists():
        raise HTTPException(404, "Source photo not found")

    try:
        client = genai.Client(api_key=api_key)
        image_bytes = src.read_bytes()

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

    out_path = UPLOADS_DIR / f"{uuid.uuid4().hex}_stylized.png"
    out_path.write_bytes(img_bytes)
    return {"stylized_path": str(out_path), "url": "/" + str(out_path)}


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
        Path(car.photo_path).unlink(missing_ok=True)
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
    if car.photo_path:
        Path(car.photo_path).unlink(missing_ok=True)
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
