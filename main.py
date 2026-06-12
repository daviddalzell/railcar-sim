import io
import json
import os
import shutil
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Optional
import uuid

from PIL import Image
from dotenv import load_dotenv
load_dotenv()

from fastapi import Depends, FastAPI, File, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from sqlalchemy import DateTime as SADateTime
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.orm import Session
from starlette.requests import Request

from database import get_db, init_db
from models import Car, CommodityCarTypeMap, Industry, Location, MovementLog, Waybill
from vision import analyze_car_photo, get_provider, OllamaVisionProvider

UPLOADS_DIR = Path("uploads")
UPLOADS_DIR.mkdir(exist_ok=True)

_PROMPTS_DIR = Path("prompts")

def _load_stylize_config() -> dict:
    p = _PROMPTS_DIR / "stylize_car.json"
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
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

app = FastAPI(title="Rail Car Movement Simulator")
app.mount("/static", StaticFiles(directory="static"), name="static")
app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")
templates = Jinja2Templates(directory="templates")


@app.on_event("startup")
def on_startup():
    init_db()
    try:
        provider = get_provider()
    except ValueError:
        provider = None
    if isinstance(provider, OllamaVisionProvider):
        provider.ensure_ready()


# ── HTML shell ────────────────────────────────────────────────────────────────

_PROVIDER_LABELS = {
    "anthropic": "Claude Vision",
    "openai": "OpenAI Vision",
    "ollama": f"Ollama ({os.environ.get('OLLAMA_MODEL', 'llava')})",
    "gemini": f"Gemini ({os.environ.get('GEMINI_MODEL', 'gemini-3.1-flash-lite')})",
}

@app.get("/")
def index(request: Request):
    provider = os.environ.get("VISION_PROVIDER", "anthropic")
    vision_label = _PROVIDER_LABELS.get(provider, f"{provider} Vision")
    return templates.TemplateResponse(
        "index.html", {"request": request, "vision_label": vision_label}
    )


# ── Pydantic schemas ──────────────────────────────────────────────────────────

class CarCreate(BaseModel):
    car_type: str
    color: str = ""
    car_number: str = ""
    reporting_marks: str = ""
    photo_path: str = ""
    current_location_id: Optional[int] = None


class CarUpdate(BaseModel):
    car_type: Optional[str] = None
    color: Optional[str] = None
    car_number: Optional[str] = None
    reporting_marks: Optional[str] = None
    current_location_id: Optional[int] = None
    photo_path: Optional[str] = None


class LocationCreate(BaseModel):
    name: str
    location_type: str = "yard"


class IndustryCreate(BaseModel):
    name: str
    location_id: Optional[int] = None
    accepted_car_types: str = ""
    commodities: str = ""
    industry_role: str = "consumer"


class WaybillCreate(BaseModel):
    name: str = ""
    origin_id: Optional[int] = None
    destination_id: Optional[int] = None
    industry_id: Optional[int] = None
    commodity: str = ""
    is_empty: bool = False
    required_car_type: Optional[str] = None


class GenerateWaybillsRequest(BaseModel):
    origin_location_id: int
    replace: bool = False


class CommodityCarTypeMapCreate(BaseModel):
    commodity: str
    car_type: str


class CommodityCarTypeMapUpdate(BaseModel):
    car_type: str


class CarSlotAssignment(BaseModel):
    slot_index: int
    waybill_id: Optional[int] = None


class CarSlotsUpdate(BaseModel):
    slots: list[CarSlotAssignment]


# ── Helpers ───────────────────────────────────────────────────────────────────

def car_to_dict(car: Car) -> dict:
    active = next((w for w in car.waybills if w.slot_index == car.active_waybill_slot), None)
    return {
        "id": car.id,
        "car_type": car.car_type,
        "color": car.color,
        "car_number": car.car_number,
        "reporting_marks": car.reporting_marks,
        "photo_path": car.photo_path,
        "current_location_id": car.current_location_id,
        "current_location_name": car.current_location.name if car.current_location else None,
        "active_waybill_slot": car.active_waybill_slot,
        "active_waybill": waybill_to_dict(active) if active else None,
        "waybill_count": len(car.waybills),
    }


def commodity_map_to_dict(m: CommodityCarTypeMap) -> dict:
    return {"id": m.id, "commodity": m.commodity, "car_type": m.car_type}


def waybill_to_dict(w: Waybill) -> dict:
    return {
        "id": w.id,
        "name": w.name,
        "car_id": w.car_id,
        "car_name": (
            f"{w.car.reporting_marks or '—'} {w.car.car_number or ''}".strip()
            if w.car else None
        ),
        "slot_index": w.slot_index,
        "origin_id": w.origin_id,
        "origin_name": w.origin.name if w.origin else None,
        "destination_id": w.destination_id,
        "destination_name": w.destination.name if w.destination else None,
        "industry_id": w.industry_id,
        "industry_name": w.industry.name if w.industry else None,
        "commodity": w.commodity,
        "is_empty": w.is_empty,
        "required_car_type": w.required_car_type,
    }


# ── Export / Import helpers ───────────────────────────────────────────────────

def _row_to_dict(obj) -> dict:
    result = {}
    for col in sa_inspect(type(obj)).columns:
        val = getattr(obj, col.key)
        if isinstance(val, datetime):
            val = val.isoformat()
        result[col.key] = val
    return result


def _import_table(db: Session, model, rows: list) -> None:
    mapper = sa_inspect(model)
    valid_keys    = {col.key for col in mapper.columns}
    datetime_keys = {col.key for col in mapper.columns if isinstance(col.type, SADateTime)}
    for row in rows:
        filtered = {
            k: (datetime.fromisoformat(v) if k in datetime_keys and isinstance(v, str) else v)
            for k, v in row.items() if k in valid_keys
        }
        db.execute(model.__table__.insert().values(**filtered))
    db.flush()


# ── Cars ──────────────────────────────────────────────────────────────────────

@app.get("/api/cars")
def list_cars(db: Session = Depends(get_db)):
    cars = db.query(Car).all()
    return [car_to_dict(c) for c in cars]


@app.post("/api/cars/upload")
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


class AnalyzePhotoRequest(BaseModel):
    photo_path: str

@app.post("/api/cars/analyze-photo")
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


class StylizeRequest(BaseModel):
    photo_path: str


@app.post("/api/cars/stylize")
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

        response = client.models.generate_content(
            model=STYLIZE_MODEL,
            contents=[
                types.Part.from_bytes(data=image_bytes, mime_type="image/jpeg"),
                STYLIZE_PROMPT,
            ],
            config=types.GenerateContentConfig(
                response_modalities=["IMAGE", "TEXT"],
            ),
        )

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


@app.post("/api/cars", status_code=201)
def create_car(data: CarCreate, db: Session = Depends(get_db)):
    car = Car(**data.model_dump())
    db.add(car)
    db.commit()
    db.refresh(car)
    return car_to_dict(car)


@app.put("/api/cars/{car_id}")
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


@app.delete("/api/cars/{car_id}", status_code=204)
def delete_car(car_id: int, db: Session = Depends(get_db)):
    car = db.get(Car, car_id)
    if not car:
        raise HTTPException(404, "Car not found")
    if car.photo_path:
        Path(car.photo_path).unlink(missing_ok=True)
    db.delete(car)
    db.commit()


@app.post("/api/cars/{car_id}/advance")
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


@app.put("/api/cars/{car_id}/location")
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


# ── Waybill pool ──────────────────────────────────────────────────────────────

@app.get("/api/waybills")
def list_waybills(db: Session = Depends(get_db)):
    return [waybill_to_dict(w) for w in db.query(Waybill).all()]


@app.post("/api/waybills", status_code=201)
def create_waybill(data: WaybillCreate, db: Session = Depends(get_db)):
    w = Waybill(**data.model_dump())
    db.add(w)
    db.commit()
    db.refresh(w)
    return waybill_to_dict(w)


@app.put("/api/waybills/{waybill_id}")
def update_waybill(waybill_id: int, data: WaybillCreate, db: Session = Depends(get_db)):
    w = db.get(Waybill, waybill_id)
    if not w:
        raise HTTPException(404, "Waybill not found")
    for field, value in data.model_dump().items():
        setattr(w, field, value)
    db.commit()
    db.refresh(w)
    return waybill_to_dict(w)


@app.delete("/api/waybills/{waybill_id}", status_code=204)
def delete_waybill(waybill_id: int, db: Session = Depends(get_db)):
    w = db.get(Waybill, waybill_id)
    if not w:
        raise HTTPException(404, "Waybill not found")
    db.delete(w)
    db.commit()


@app.get("/api/cars/{car_id}/waybills")
def get_car_waybills(car_id: int, db: Session = Depends(get_db)):
    car = db.get(Car, car_id)
    if not car:
        raise HTTPException(404, "Car not found")
    return [waybill_to_dict(w) for w in car.waybills]


@app.put("/api/cars/{car_id}/slots")
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


# ── Locations ─────────────────────────────────────────────────────────────────

@app.get("/api/locations")
def list_locations(db: Session = Depends(get_db)):
    return [
        {"id": l.id, "name": l.name, "location_type": l.location_type}
        for l in db.query(Location).all()
    ]


@app.post("/api/locations", status_code=201)
def create_location(data: LocationCreate, db: Session = Depends(get_db)):
    loc = Location(**data.model_dump())
    db.add(loc)
    db.commit()
    db.refresh(loc)
    return {"id": loc.id, "name": loc.name, "location_type": loc.location_type}


@app.put("/api/locations/{loc_id}")
def update_location(loc_id: int, data: LocationCreate, db: Session = Depends(get_db)):
    loc = db.get(Location, loc_id)
    if not loc:
        raise HTTPException(404, "Location not found")
    loc.name = data.name
    loc.location_type = data.location_type
    db.commit()
    return {"id": loc.id, "name": loc.name, "location_type": loc.location_type}


@app.delete("/api/locations/{loc_id}", status_code=204)
def delete_location(loc_id: int, db: Session = Depends(get_db)):
    loc = db.get(Location, loc_id)
    if not loc:
        raise HTTPException(404, "Location not found")
    db.delete(loc)
    db.commit()


# ── Industries ────────────────────────────────────────────────────────────────

@app.get("/api/industries")
def list_industries(db: Session = Depends(get_db)):
    return [
        {
            "id": i.id,
            "name": i.name,
            "location_id": i.location_id,
            "location_name": i.location.name if i.location else None,
            "accepted_car_types": i.accepted_car_types,
            "commodities": i.commodities,
            "industry_role": i.industry_role,
        }
        for i in db.query(Industry).all()
    ]


@app.post("/api/industries", status_code=201)
def create_industry(data: IndustryCreate, db: Session = Depends(get_db)):
    ind = Industry(**data.model_dump())
    db.add(ind)
    db.commit()
    db.refresh(ind)
    return {"id": ind.id, "name": ind.name, "location_id": ind.location_id,
            "accepted_car_types": ind.accepted_car_types, "commodities": ind.commodities,
            "industry_role": ind.industry_role}


@app.put("/api/industries/{ind_id}")
def update_industry(ind_id: int, data: IndustryCreate, db: Session = Depends(get_db)):
    ind = db.get(Industry, ind_id)
    if not ind:
        raise HTTPException(404, "Industry not found")
    for field, value in data.model_dump().items():
        setattr(ind, field, value)
    db.commit()
    return {"id": ind.id, "name": ind.name, "location_id": ind.location_id,
            "accepted_car_types": ind.accepted_car_types, "commodities": ind.commodities,
            "industry_role": ind.industry_role}


@app.delete("/api/industries/{ind_id}", status_code=204)
def delete_industry(ind_id: int, db: Session = Depends(get_db)):
    ind = db.get(Industry, ind_id)
    if not ind:
        raise HTTPException(404, "Industry not found")
    db.delete(ind)
    db.commit()


# ── Commodity Car Type Map ────────────────────────────────────────────────────

_DEFAULT_COMMODITY_MAP = [
    ("lumber", "flatcar"), ("logs", "flatcar"), ("steel coils", "flatcar"), ("pipe", "flatcar"),
    ("grain", "covered hopper"), ("wheat", "covered hopper"), ("corn", "covered hopper"), ("flour", "covered hopper"),
    ("coal", "hopper"), ("gravel", "hopper"), ("sand", "hopper"), ("ballast", "hopper"),
    ("fuel oil", "tank car"), ("crude oil", "tank car"), ("chemicals", "tank car"), ("gasoline", "tank car"),
    ("produce", "refrigerator car"), ("meat", "refrigerator car"), ("frozen goods", "refrigerator car"),
    ("merchandise", "boxcar"), ("auto parts", "boxcar"), ("paper", "boxcar"), ("canned goods", "boxcar"),
    ("steel", "gondola"), ("scrap metal", "gondola"), ("machinery", "gondola"),
]


@app.get("/api/commodity-car-type-map")
def list_commodity_map(db: Session = Depends(get_db)):
    rows = db.query(CommodityCarTypeMap).order_by(CommodityCarTypeMap.commodity).all()
    return [commodity_map_to_dict(r) for r in rows]


@app.post("/api/commodity-car-type-map/seed", status_code=201)
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


@app.post("/api/commodity-car-type-map", status_code=201)
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


@app.put("/api/commodity-car-type-map/{map_id}")
def update_commodity_map(map_id: int, data: CommodityCarTypeMapUpdate, db: Session = Depends(get_db)):
    entry = db.get(CommodityCarTypeMap, map_id)
    if not entry:
        raise HTTPException(404, "Mapping not found")
    entry.car_type = data.car_type.strip().lower()
    db.commit()
    db.refresh(entry)
    return commodity_map_to_dict(entry)


@app.delete("/api/commodity-car-type-map/{map_id}", status_code=204)
def delete_commodity_map(map_id: int, db: Session = Depends(get_db)):
    entry = db.get(CommodityCarTypeMap, map_id)
    if not entry:
        raise HTTPException(404, "Mapping not found")
    db.delete(entry)
    db.commit()


# ── Automation ───────────────────────────────────────────────────────────────

_WILDCARD_TYPES = {"all", "any", ""}
_ALWAYS_EMPTY_RETURN_TYPES = {"tank car", "hopper", "covered hopper"}


def _car_type_matches(required: Optional[str], car_type: str) -> bool:
    if not required or required.lower() in _WILDCARD_TYPES:
        return True
    r = required.lower()
    c = car_type.lower()
    return r == c or r in c or c in r


def _find_loaded_from(unassigned, location_id, car_type):
    return next(
        (w for w in unassigned
         if not w.is_empty
         and w.origin_id == location_id
         and w.destination_id is not None
         and _car_type_matches(w.required_car_type, car_type)),
        None,
    )


def _find_empty_to_staging(unassigned, location_id, staging_ids, car_type):
    return next(
        (w for w in unassigned
         if w.is_empty
         and w.origin_id == location_id
         and w.destination_id in staging_ids
         and _car_type_matches(w.required_car_type, car_type)),
        None,
    )


def _find_any_from(unassigned, location_id, car_type):
    return next(
        (w for w in unassigned
         if w.origin_id == location_id
         and w.destination_id is not None
         and _car_type_matches(w.required_car_type, car_type)),
        None,
    )


def _find_best_staging_for_car(unassigned, staging_ids, car_type, loaded_only=False):
    counts = {}
    for w in unassigned:
        if loaded_only and w.is_empty:
            continue
        if (w.origin_id in staging_ids
                and w.destination_id is not None
                and _car_type_matches(w.required_car_type, car_type)):
            counts[w.origin_id] = counts.get(w.origin_id, 0) + 1
    if not counts:
        return None
    return max(counts, key=lambda k: counts[k])


@app.post("/api/generate-waybills")
def generate_waybills(data: GenerateWaybillsRequest, db: Session = Depends(get_db)):
    if data.replace:
        db.query(Waybill).delete(synchronize_session=False)
        db.commit()

    industries = db.query(Industry).all()
    map_rows = db.query(CommodityCarTypeMap).all()
    commodity_map = {r.commodity: r.car_type for r in map_rows}

    created = 0
    skipped = 0
    new_waybills = []

    for ind in industries:
        if not ind.location_id:
            continue
        commodities = [c.strip() for c in ind.commodities.split(",") if c.strip()]
        if not commodities:
            continue

        raw_types = [t.strip() for t in ind.accepted_car_types.split(",") if t.strip()]
        industry_fallback = None if not raw_types or raw_types[0].lower() in _WILDCARD_TYPES else raw_types[0]
        role = getattr(ind, "industry_role", "consumer")

        def _wb_exists(name, _ind_id=ind.id):
            return db.query(Waybill).filter(
                Waybill.industry_id == _ind_id, Waybill.name == name
            ).first()

        def _add(wb):
            nonlocal created
            db.add(wb)
            db.flush()
            new_waybills.append(wb)
            created += 1

        if role == "producer":
            for commodity in commodities:
                req_type = commodity_map.get(commodity.lower(), industry_fallback)
                out_name = f"{commodity} ← {ind.name}"
                if not _wb_exists(out_name):
                    _add(Waybill(
                        name=out_name,
                        origin_id=ind.location_id,
                        destination_id=data.origin_location_id,
                        industry_id=ind.id,
                        commodity=commodity,
                        required_car_type=req_type,
                        is_empty=False,
                    ))
                else:
                    skipped += 1

        elif role == "transload":
            for commodity in commodities:
                req_type = commodity_map.get(commodity.lower(), industry_fallback)
                in_name = f"{commodity} → {ind.name}"
                out_name = f"{commodity} ← {ind.name}"
                if not _wb_exists(in_name):
                    _add(Waybill(
                        name=in_name,
                        origin_id=data.origin_location_id,
                        destination_id=ind.location_id,
                        industry_id=ind.id,
                        commodity=commodity,
                        required_car_type=req_type,
                        is_empty=False,
                    ))
                else:
                    skipped += 1
                if not _wb_exists(out_name):
                    _add(Waybill(
                        name=out_name,
                        origin_id=ind.location_id,
                        destination_id=data.origin_location_id,
                        industry_id=ind.id,
                        commodity=commodity,
                        required_car_type=req_type,
                        is_empty=False,
                    ))
                else:
                    skipped += 1

        else:  # consumer (default)
            for commodity in commodities:
                req_type = commodity_map.get(commodity.lower(), industry_fallback)
                in_name = f"{commodity} → {ind.name}"
                if not _wb_exists(in_name):
                    _add(Waybill(
                        name=in_name,
                        origin_id=data.origin_location_id,
                        destination_id=ind.location_id,
                        industry_id=ind.id,
                        commodity=commodity,
                        required_car_type=req_type,
                        is_empty=False,
                    ))
                else:
                    skipped += 1

        # Empty waybills — one per accepted car type (or one generic if wildcard)
        empty_types = [ct for ct in raw_types if ct.lower() not in _WILDCARD_TYPES] if raw_types else []

        # Empty return (industry → staging) for all roles
        if empty_types:
            for ct in empty_types:
                n = f"← {ind.name} (empty {ct})"
                if not _wb_exists(n):
                    _add(Waybill(name=n, origin_id=ind.location_id,
                        destination_id=data.origin_location_id, industry_id=ind.id,
                        commodity="", required_car_type=ct, is_empty=True))
                else:
                    skipped += 1
        else:
            n = f"← {ind.name} (empty)"
            if not _wb_exists(n):
                _add(Waybill(name=n, origin_id=ind.location_id,
                    destination_id=data.origin_location_id, industry_id=ind.id,
                    commodity="", required_car_type=None, is_empty=True))

        # Empty delivery (staging → industry) for shipping roles (producer + transload)
        if role in ("producer", "transload"):
            if empty_types:
                for ct in empty_types:
                    n = f"→ {ind.name} (empty {ct})"
                    if not _wb_exists(n):
                        _add(Waybill(name=n, origin_id=data.origin_location_id,
                            destination_id=ind.location_id, industry_id=ind.id,
                            commodity="", required_car_type=ct, is_empty=True))
                    else:
                        skipped += 1
            else:
                n = f"→ {ind.name} (empty)"
                if not _wb_exists(n):
                    _add(Waybill(name=n, origin_id=data.origin_location_id,
                        destination_id=ind.location_id, industry_id=ind.id,
                        commodity="", required_car_type=industry_fallback, is_empty=True))

    db.commit()
    for w in new_waybills:
        db.refresh(w)
    return {"created": created, "skipped": skipped, "waybills": [waybill_to_dict(w) for w in new_waybills]}


@app.post("/api/auto-assign-waybills")
def auto_assign_waybills(db: Session = Depends(get_db)):
    cars = db.query(Car).all()
    unassigned = db.query(Waybill).filter(Waybill.car_id.is_(None)).all()

    staging_ids = {
        loc.id for loc in
        db.query(Location).filter(Location.location_type == "staging").all()
    }
    if not staging_ids:
        return {"assigned": 0, "cars_updated": [car_to_dict(c) for c in cars]}

    assigned = 0

    for car in cars:
        occupied = {w.slot_index for w in car.waybills if w.slot_index is not None}
        open_slots = [s for s in range(4) if s not in occupied]
        if not open_slots:
            continue

        always_empty = any(t in car.car_type.lower() for t in _ALWAYS_EMPTY_RETURN_TYPES)

        if not car.waybills:
            current_loc = _find_best_staging_for_car(unassigned, staging_ids, car.car_type, loaded_only=always_empty)
            if current_loc is None:
                continue
        else:
            filled = sorted(w.slot_index for w in car.waybills if w.slot_index is not None)
            last = filled[-1]
            expected = list(range(last + 1, last + 1 + len(open_slots)))
            if open_slots != expected:
                continue
            last_wb = next((w for w in car.waybills if w.slot_index == last), None)
            if last_wb is None or last_wb.destination_id is None:
                continue
            current_loc = last_wb.destination_id

        for slot in open_slots:
            if current_loc in staging_ids:
                if always_empty:
                    candidate = _find_loaded_from(unassigned, current_loc, car.car_type)
                else:
                    candidate = _find_any_from(unassigned, current_loc, car.car_type)
            elif always_empty:
                candidate = _find_empty_to_staging(unassigned, current_loc, staging_ids, car.car_type)
            else:
                candidate = (
                    _find_loaded_from(unassigned, current_loc, car.car_type)
                    or _find_empty_to_staging(unassigned, current_loc, staging_ids, car.car_type)
                )

            if candidate is None:
                break

            if candidate.is_empty:
                clone = Waybill(
                    name=candidate.name,
                    origin_id=candidate.origin_id,
                    destination_id=candidate.destination_id,
                    industry_id=candidate.industry_id,
                    commodity=candidate.commodity,
                    required_car_type=candidate.required_car_type,
                    is_empty=True,
                    car_id=car.id,
                    slot_index=slot,
                )
                db.add(clone)
                db.flush()
            else:
                candidate.car_id = car.id
                candidate.slot_index = slot
                unassigned.remove(candidate)

            assigned += 1
            current_loc = candidate.destination_id
            if current_loc is None:
                break

    db.commit()
    for car in cars:
        db.refresh(car)
    return {"assigned": assigned, "cars_updated": [car_to_dict(c) for c in cars]}


# ── Upload library ───────────────────────────────────────────────────────────

@app.get("/api/uploads")
def list_uploads(db: Session = Depends(get_db)):
    assigned = {car.photo_path for car in db.query(Car).all() if car.photo_path}
    files = []
    for f in sorted(UPLOADS_DIR.iterdir(), key=lambda x: x.stat().st_mtime, reverse=True):
        if f.is_file() and f.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp", ".gif"):
            files.append({
                "path": str(f),
                "url": "/" + str(f),
                "assigned": str(f) in assigned,
            })
    return files


@app.post("/api/uploads/purge")
def purge_uploads(db: Session = Depends(get_db)):
    assigned = {car.photo_path for car in db.query(Car).all() if car.photo_path}
    deleted = 0
    for f in UPLOADS_DIR.iterdir():
        if f.is_file() and str(f) not in assigned:
            f.unlink(missing_ok=True)
            deleted += 1
    return {"deleted": deleted}


class DeleteUploadRequest(BaseModel):
    path: str

@app.post("/api/uploads/delete", status_code=204)
def delete_upload(data: DeleteUploadRequest):
    target = Path(data.path).resolve()
    uploads_resolved = UPLOADS_DIR.resolve()
    if not str(target).startswith(str(uploads_resolved)):
        raise HTTPException(400, "Path outside uploads directory")
    if not target.name.endswith("_stylized.png"):
        raise HTTPException(400, "Only stylized images may be deleted this way")
    target.unlink(missing_ok=True)


# ── Operating Session ────────────────────────────────────────────────────────

def _get_active_waybill(car: Car):
    return next((w for w in car.waybills if w.slot_index == car.active_waybill_slot), None)


def _advance_slot(car: Car) -> int:
    assigned = sorted(w.slot_index for w in car.waybills if w.slot_index is not None)
    if not assigned:
        return car.active_waybill_slot
    try:
        idx = assigned.index(car.active_waybill_slot)
        return assigned[(idx + 1) % len(assigned)]
    except ValueError:
        return assigned[0]


def _build_session_plan(db: Session) -> dict:
    # staging + yard both act as dispatch points (trains originate/terminate there)
    dispatch_ids = {l.id for l in db.query(Location).filter(
        Location.location_type.in_(["staging", "yard"])
    ).all()}
    arrivals, departures, warnings = [], [], []

    for car in db.query(Car).all():
        wb = _get_active_waybill(car)
        if not wb or wb.destination_id is None:
            continue
        if car.current_location_id != wb.destination_id:
            if car.current_location_id in dispatch_ids:
                arrivals.append(car)
            else:
                departures.append(car)

    arrivals   = sorted(arrivals,   key=lambda c: c.id)[:5]
    departures = sorted(departures, key=lambda c: c.id)[:min(5, max(len(arrivals), len(departures)))]

    if len(departures) < len(arrivals):
        warnings.append(
            f"Only {len(departures)} outbound car(s) available but {len(arrivals)} arrival(s) planned."
        )
    if not arrivals:
        warnings.append("No inbound cars (cars at yard/staging needing a move) available.")
    if not departures:
        warnings.append("No outbound cars (cars at industries needing a move) available.")

    def _enrich(car):
        d = car_to_dict(car)
        wb = _get_active_waybill(car)
        d["session_from_location_name"] = car.current_location.name if car.current_location else None
        d["session_to_location_name"]   = wb.destination.name if wb and wb.destination else None
        return d

    return {
        "arrivals":   [_enrich(c) for c in arrivals],
        "departures": [_enrich(c) for c in departures],
        "warnings":   warnings,
    }


@app.post("/api/session/plan")
def session_plan(db: Session = Depends(get_db)):
    return _build_session_plan(db)


class SessionCarResult(BaseModel):
    car_id: int
    status: str                    # "done" or "cp"
    location_id: Optional[int] = None  # required for cp cars


class SessionEndRequest(BaseModel):
    cars: list[SessionCarResult]


@app.post("/api/session/end")
def session_end(req: SessionEndRequest, db: Session = Depends(get_db)):
    updated = []
    for item in req.cars:
        car = db.get(Car, item.car_id)
        if not car:
            continue
        wb = _get_active_waybill(car)
        old_loc = car.current_location_id
        if item.status == "done" and wb and wb.destination_id:
            car.current_location_id = wb.destination_id
            db.add(MovementLog(car_id=car.id, from_location_id=old_loc,
                               to_location_id=wb.destination_id, note="Session move"))
            car.active_waybill_slot = _advance_slot(car)
        elif item.status == "cp" and item.location_id:
            car.current_location_id = item.location_id
            db.add(MovementLog(car_id=car.id, from_location_id=old_loc,
                               to_location_id=item.location_id, note="Session CP"))
            # waybill NOT advanced for CP cars
        db.commit()
        db.refresh(car)
        updated.append(car_to_dict(car))
    return {"updated": updated}


# ── Operations ────────────────────────────────────────────────────────────────

@app.get("/api/operations")
def operations(db: Session = Depends(get_db)):
    cars = db.query(Car).all()
    result = []
    for car in cars:
        d = car_to_dict(car)
        logs = (
            db.query(MovementLog)
            .filter(MovementLog.car_id == car.id)
            .order_by(MovementLog.timestamp.desc())
            .limit(5)
            .all()
        )
        d["recent_moves"] = [
            {
                "timestamp": log.timestamp.isoformat(),
                "from_location_id": log.from_location_id,
                "to_location_id": log.to_location_id,
                "note": log.note,
            }
            for log in logs
        ]
        result.append(d)
    return result


# ── Export / Import ───────────────────────────────────────────────────────────

@app.get("/api/export")
def export_data(db: Session = Depends(get_db)):
    from datetime import date as _date
    tables = {
        "locations":              [_row_to_dict(r) for r in db.query(Location).all()],
        "industries":             [_row_to_dict(r) for r in db.query(Industry).all()],
        "commodity_car_type_map": [_row_to_dict(r) for r in db.query(CommodityCarTypeMap).all()],
        "cars":                   [_row_to_dict(r) for r in db.query(Car).all()],
        "waybills":               [_row_to_dict(r) for r in db.query(Waybill).all()],
        "movement_logs":          [_row_to_dict(r) for r in db.query(MovementLog).all()],
    }
    payload = {"version": 1, "exported_at": datetime.utcnow().isoformat(), "tables": tables}
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("data.json", json.dumps(payload, indent=2))
        for car_row in tables["cars"]:
            photo = car_row.get("photo_path") or ""
            if photo and Path(photo).exists():
                zf.write(photo, arcname=f"photos/{Path(photo).name}")
    buf.seek(0)
    filename = f"railcar-backup-{_date.today().isoformat()}.zip"
    return StreamingResponse(buf, media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@app.post("/api/import")
async def import_data(file: UploadFile = File(...), db: Session = Depends(get_db)):
    if not (file.filename or "").endswith(".zip"):
        raise HTTPException(400, "File must be a .zip archive")
    content = await file.read()
    try:
        zf = zipfile.ZipFile(io.BytesIO(content))
    except zipfile.BadZipFile:
        raise HTTPException(400, "Invalid ZIP file")
    try:
        payload = json.loads(zf.read("data.json"))
    except KeyError:
        raise HTTPException(400, "ZIP does not contain data.json")
    tables = payload.get("tables", {})

    # Restore photos before clearing DB
    for name in zf.namelist():
        if name.startswith("photos/") and name != "photos/":
            (UPLOADS_DIR / Path(name).name).write_bytes(zf.read(name))

    # Clear in reverse FK order
    db.query(MovementLog).delete(synchronize_session=False)
    db.query(Waybill).delete(synchronize_session=False)
    db.query(Car).delete(synchronize_session=False)
    db.query(CommodityCarTypeMap).delete(synchronize_session=False)
    db.query(Industry).delete(synchronize_session=False)
    db.query(Location).delete(synchronize_session=False)
    db.flush()

    # Insert in FK order
    _import_table(db, Location,            tables.get("locations", []))
    _import_table(db, Industry,            tables.get("industries", []))
    _import_table(db, CommodityCarTypeMap, tables.get("commodity_car_type_map", []))
    _import_table(db, Car,                 tables.get("cars", []))
    _import_table(db, Waybill,             tables.get("waybills", []))
    _import_table(db, MovementLog,         tables.get("movement_logs", []))
    db.commit()
    return {"ok": True}
