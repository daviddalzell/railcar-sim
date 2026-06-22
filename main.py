import csv
import io
import json
import os
import shutil
import time
import xml.etree.ElementTree as ET
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
from models import Car, CarType, CommodityCarTypeMap, DispatchPlan, Industry, LayoutSettings, Location, MovementLog, SessionClock, SwitchingArea, Waybill
from vision import analyze_car_photo, get_provider, OllamaVisionProvider, call_with_retry

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

app = FastAPI(title="Waypoint")
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
    switching_area_id: Optional[int] = None


class SwitchingAreaCreate(BaseModel):
    name: str
    car_capacity: int = 10


class DispatchBuildRequest(BaseModel):
    origin_location_id: int
    switching_area_id: int


class IndustryCreate(BaseModel):
    name: str
    location_id: int
    accepted_car_types: str = ""
    commodities: str = ""
    industry_role: str = "consumer"
    inbound_car_types: str = ""
    outbound_commodities: str = ""
    outbound_car_types: str = ""


class WaybillCreate(BaseModel):
    name: str = ""
    origin_id: Optional[int] = None
    destination_id: Optional[int] = None
    industry_id: Optional[int] = None
    commodity: str = ""
    is_empty: bool = False
    required_car_type: Optional[str] = None


class CarTypeCreate(BaseModel):
    name: str


class CarImportRow(BaseModel):
    reporting_marks: str
    car_number: str
    car_type: str = "other"
    color: str = ""


class CarImportCommit(BaseModel):
    cars: list[CarImportRow]
    mode: str = "add"


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


def industry_to_dict(i: Industry) -> dict:
    return {
        "id": i.id,
        "name": i.name,
        "location_id": i.location_id,
        "location_name": i.location.name if i.location else None,
        "accepted_car_types": i.accepted_car_types,
        "commodities": i.commodities,
        "industry_role": i.industry_role,
        "inbound_car_types": i.inbound_car_types,
        "outbound_commodities": i.outbound_commodities,
        "outbound_car_types": i.outbound_car_types,
    }


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


def switching_area_to_dict(area: SwitchingArea, db: Session) -> dict:
    loc_ids = [l.id for l in area.locations]
    current_count = db.query(Car).filter(Car.current_location_id.in_(loc_ids)).count() if loc_ids else 0
    dispatch_ids = {l.id for l in db.query(Location).filter(
        Location.location_type.in_(["staging", "yard"])
    ).all()}
    area_cars = db.query(Car).filter(Car.current_location_id.in_(loc_ids)).all() if loc_ids else []
    outbound_count = sum(
        1 for car in area_cars
        if (wb := _get_active_waybill(car)) and wb.destination_id in dispatch_ids
    )
    available_spots = max(0, area.car_capacity - current_count + outbound_count)
    return {
        "id": area.id,
        "name": area.name,
        "car_capacity": area.car_capacity,
        "current_car_count": current_count,
        "available_spots": available_spots,
        "locations": [{"id": l.id, "name": l.name, "location_type": l.location_type} for l in area.locations],
    }


def dispatch_plan_to_dict(plan: DispatchPlan, db: Session) -> dict:
    setout_ids = json.loads(plan.setout_ids_json or "[]")
    pickup_ids = json.loads(plan.pickup_ids_json or "[]")
    spots_ids  = json.loads(plan.spots_ids_json or "[]")

    def _enrich(car_id, role):
        car = db.get(Car, car_id)
        if not car:
            return None
        d = car_to_dict(car)
        d["role"] = role
        return d

    setouts = [d for cid in setout_ids if (d := _enrich(cid, "setout"))]
    pickups = [d for cid in pickup_ids if (d := _enrich(cid, "pickup"))]
    spots   = [d for cid in spots_ids  if (d := _enrich(cid, "spot"))]

    origin = db.get(Location, plan.origin_location_id) if plan.origin_location_id else None
    area = db.get(SwitchingArea, plan.switching_area_id) if plan.switching_area_id else None

    return {
        "plan_type": plan.plan_type,
        "origin_location_id": plan.origin_location_id,
        "origin_name": origin.name if origin else None,
        "switching_area_id": plan.switching_area_id,
        "switching_area_name": area.name if area else None,
        "setouts": setouts,
        "pickups": pickups,
        "spots": spots,
        "available_spots": plan.available_spots,
        "built_at": plan.built_at,
        "warnings": [],
    }


def _clear_dispatch_plan(db: Session):
    plan = db.get(DispatchPlan, 1)
    if plan:
        db.delete(plan)
        db.commit()


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


# ── Car import helpers ────────────────────────────────────────────────────────

CAR_TYPE_MAP = {
    "box car": "boxcar", "boxcar": "boxcar",
    "flat": "flatcar", "flat car": "flatcar", "flatcar": "flatcar",
    "tank": "tank car", "tank car": "tank car",
    "covered hopper": "covered hopper", "cov hopper": "covered hopper",
    "gondola": "gondola",
    "hopper": "hopper", "coal car": "hopper",
    "caboose": "caboose",
    "passenger": "passenger car", "coach": "passenger car", "passenger car": "passenger car",
    "refrigerator": "refrigerator car", "reefer": "refrigerator car",
    "refrigerator car": "refrigerator car", "reefer car": "refrigerator car",
    "auto rack": "other", "autorack": "other",
}

CSV_FIELD_ALIASES = {
    "reporting_marks": {"reporting_marks", "road", "marks", "railroad"},
    "car_number":      {"car_number", "number", "no", "num"},
    "car_type":        {"car_type", "type", "kind"},
    "color":           {"color", "colour"},
}


def normalise_car_type(raw: str) -> str:
    return CAR_TYPE_MAP.get(raw.strip().lower(), "other")


def parse_csv_cars(content: str) -> tuple[list[dict], list[str]]:
    rows, errors = [], []
    reader = csv.DictReader(io.StringIO(content))
    if not reader.fieldnames:
        return rows, ["CSV appears to be empty or has no header row"]
    col_map = {}
    for field, aliases in CSV_FIELD_ALIASES.items():
        for header in (reader.fieldnames or []):
            if header.strip().lower() in aliases:
                col_map[field] = header
                break
    for i, row in enumerate(reader, start=2):
        marks = row.get(col_map.get("reporting_marks", ""), "").strip()
        number = row.get(col_map.get("car_number", ""), "").strip()
        if not marks or not number:
            errors.append(f"Row {i}: missing {'road' if not marks else 'number'} — skipped")
            continue
        rows.append({
            "reporting_marks": marks,
            "car_number": number,
            "car_type": normalise_car_type(row.get(col_map.get("car_type", ""), "")),
            "color": row.get(col_map.get("color", ""), "").strip(),
        })
    return rows, errors


def parse_jmri_cars(content: str) -> tuple[list[dict], list[str]]:
    rows, errors = [], []
    try:
        root = ET.fromstring(content)
    except ET.ParseError as e:
        return rows, [f"XML parse error: {e}"]
    for i, car in enumerate(root.iter("car"), start=1):
        marks  = (car.get("road") or car.get("roadName") or "").strip()
        number = (car.get("number") or car.get("roadNumber") or "").strip()
        if not marks or not number:
            errors.append(f"Car {i}: missing road or number — skipped")
            continue
        rows.append({
            "reporting_marks": marks,
            "car_number": number,
            "car_type": normalise_car_type(car.get("type", "")),
            "color": (car.get("color") or "").strip(),
        })
    return rows, errors


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
    for w in car.waybills:
        w.car_id = None
        w.slot_index = None
    db.query(MovementLog).filter(MovementLog.car_id == car_id).delete(synchronize_session=False)
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

def _location_to_dict(l: Location) -> dict:
    return {
        "id": l.id,
        "name": l.name,
        "location_type": l.location_type,
        "switching_area_id": l.switching_area_id,
    }


@app.get("/api/locations")
def list_locations(db: Session = Depends(get_db)):
    return [_location_to_dict(l) for l in db.query(Location).all()]


@app.post("/api/locations", status_code=201)
def create_location(data: LocationCreate, db: Session = Depends(get_db)):
    loc = Location(**data.model_dump())
    db.add(loc)
    db.commit()
    db.refresh(loc)
    return _location_to_dict(loc)


@app.put("/api/locations/{loc_id}")
def update_location(loc_id: int, data: LocationCreate, db: Session = Depends(get_db)):
    loc = db.get(Location, loc_id)
    if not loc:
        raise HTTPException(404, "Location not found")
    loc.name = data.name
    loc.location_type = data.location_type
    loc.switching_area_id = data.switching_area_id
    db.commit()
    return _location_to_dict(loc)


@app.delete("/api/locations/{loc_id}")
def delete_location(loc_id: int, merge_into_id: Optional[int] = None, db: Session = Depends(get_db)):
    loc = db.get(Location, loc_id)
    if not loc:
        raise HTTPException(404, "Location not found")

    if loc.location_type == "staging":
        if merge_into_id is None:
            raise HTTPException(400, "Staging locations require a merge target")
        target = db.get(Location, merge_into_id)
        if not target or target.location_type != "staging":
            raise HTTPException(400, "Merge target must be a staging location")
        db.query(Car).filter(Car.current_location_id == loc_id).update({"current_location_id": merge_into_id})
        db.query(Waybill).filter(Waybill.origin_id == loc_id).update({"origin_id": merge_into_id})
        db.query(Waybill).filter(Waybill.destination_id == loc_id).update({"destination_id": merge_into_id})
        db.query(MovementLog).filter(MovementLog.from_location_id == loc_id).update({"from_location_id": merge_into_id})
        db.query(MovementLog).filter(MovementLog.to_location_id == loc_id).update({"to_location_id": merge_into_id})
        db.flush()
        db.delete(loc)
        db.commit()
        return {"action": "merged", "into": target.name}

    else:
        blocking = db.query(Car).filter(Car.current_location_id == loc_id).all()
        if blocking:
            raise HTTPException(409, detail={
                "message": f"Cars must be moved before deleting \"{loc.name}\"",
                "cars": [{"id": c.id, "reporting_marks": c.reporting_marks,
                           "car_number": c.car_number, "car_type": c.car_type} for c in blocking]
            })
        db.query(MovementLog).filter(MovementLog.from_location_id == loc_id).update({"from_location_id": None})
        db.query(MovementLog).filter(MovementLog.to_location_id == loc_id).update({"to_location_id": None})
        db.query(Waybill).filter(
            (Waybill.origin_id == loc_id) | (Waybill.destination_id == loc_id)
        ).delete(synchronize_session=False)
        db.delete(loc)
        db.commit()
        return {"action": "deleted"}


# ── Switching Areas ───────────────────────────────────────────────────────────

@app.get("/api/switching-areas")
def list_switching_areas(db: Session = Depends(get_db)):
    areas = db.query(SwitchingArea).all()
    return [switching_area_to_dict(a, db) for a in areas]


@app.post("/api/switching-areas", status_code=201)
def create_switching_area(data: SwitchingAreaCreate, db: Session = Depends(get_db)):
    area = SwitchingArea(name=data.name, car_capacity=data.car_capacity)
    db.add(area)
    db.commit()
    db.refresh(area)
    return switching_area_to_dict(area, db)


@app.put("/api/switching-areas/{area_id}")
def update_switching_area(area_id: int, data: SwitchingAreaCreate, db: Session = Depends(get_db)):
    area = db.get(SwitchingArea, area_id)
    if not area:
        raise HTTPException(404, "Switching area not found")
    area.name = data.name
    area.car_capacity = data.car_capacity
    db.commit()
    return switching_area_to_dict(area, db)


@app.delete("/api/switching-areas/{area_id}", status_code=204)
def delete_switching_area(area_id: int, db: Session = Depends(get_db)):
    area = db.get(SwitchingArea, area_id)
    if not area:
        raise HTTPException(404, "Switching area not found")
    db.query(Location).filter(Location.switching_area_id == area_id).update(
        {"switching_area_id": None}, synchronize_session=False
    )
    db.delete(area)
    db.commit()


# ── Dispatcher ────────────────────────────────────────────────────────────────

@app.post("/api/dispatcher/build-plan")
def build_dispatch_plan(data: DispatchBuildRequest, db: Session = Depends(get_db)):
    area = db.get(SwitchingArea, data.switching_area_id)
    if not area:
        raise HTTPException(404, "Switching area not found")
    origin = db.get(Location, data.origin_location_id)
    if not origin:
        raise HTTPException(404, "Origin location not found")

    area_location_ids = {l.id for l in area.locations}
    dispatch_ids = {l.id for l in db.query(Location).filter(
        Location.location_type.in_(["staging", "yard"])
    ).all()}

    current_count = db.query(Car).filter(
        Car.current_location_id.in_(list(area_location_ids))
    ).count() if area_location_ids else 0

    area_cars = db.query(Car).filter(
        Car.current_location_id.in_(list(area_location_ids))
    ).all() if area_location_ids else []

    outbound = [
        car for car in area_cars
        if (wb := _get_active_waybill(car)) and wb.destination_id in dispatch_ids
    ]

    # Cars already inside the area that still need to be spotted to another location
    # within the area (local switching moves — don't free capacity).
    local_spots = [
        car for car in area_cars
        if (wb := _get_active_waybill(car))
        and wb.destination_id in area_location_ids
        and car.current_location_id != wb.destination_id
    ]

    available_spots = max(0, area.car_capacity - current_count + len(outbound))

    origin_cars = db.query(Car).filter(
        Car.current_location_id == data.origin_location_id
    ).all()
    inbound = [
        car for car in origin_cars
        if (wb := _get_active_waybill(car)) and wb.destination_id in area_location_ids
    ]
    consist_inbound = inbound[:available_spots]

    warnings = []
    if not consist_inbound and not outbound and not local_spots:
        warnings.append("No eligible cars found for this origin and switching area.")

    plan = db.get(DispatchPlan, 1)
    if not plan:
        plan = DispatchPlan(id=1)
        db.add(plan)

    plan.plan_type = "switching"
    plan.origin_location_id = data.origin_location_id
    plan.switching_area_id = data.switching_area_id
    plan.destination_location_id = None
    plan.setout_ids_json = json.dumps([c.id for c in consist_inbound])
    plan.pickup_ids_json = json.dumps([c.id for c in outbound])
    plan.spots_ids_json  = json.dumps([c.id for c in local_spots])
    plan.available_spots = available_spots
    plan.built_at = time.time()
    db.commit()

    result = dispatch_plan_to_dict(plan, db)
    result["warnings"] = warnings
    return result


@app.get("/api/dispatcher/plan")
def get_dispatch_plan(db: Session = Depends(get_db)):
    plan = db.get(DispatchPlan, 1)
    if not plan or plan.built_at is None:
        return None
    return dispatch_plan_to_dict(plan, db)


@app.delete("/api/dispatcher/plan", status_code=204)
def clear_dispatch_plan_endpoint(db: Session = Depends(get_db)):
    _clear_dispatch_plan(db)


# ── Layout Status ─────────────────────────────────────────────────────────────

@app.get("/api/layout-status")
def layout_status(db: Session = Depends(get_db)):
    areas = db.query(SwitchingArea).all()
    area_dicts = []
    for area in areas:
        d = switching_area_to_dict(area, db)
        loc_ids = [l.id for l in area.locations]
        cars = db.query(Car).filter(Car.current_location_id.in_(loc_ids)).all() if loc_ids else []
        d["cars"] = [_enrich_car_for_status(c) for c in cars]
        area_dicts.append(d)

    yard_locs = db.query(Location).filter(
        Location.location_type.in_(["staging", "yard"])
    ).all()
    yard_dicts = []
    for loc in yard_locs:
        cars = db.query(Car).filter(Car.current_location_id == loc.id).all()
        yard_dicts.append({
            "id": loc.id,
            "name": loc.name,
            "location_type": loc.location_type,
            "car_count": len(cars),
            "cars": [_enrich_car_for_status(c) for c in cars],
        })

    return {"switching_areas": area_dicts, "yards": yard_dicts}


def _enrich_car_for_status(car: Car) -> dict:
    wb = _get_active_waybill(car)
    return {
        "id": car.id,
        "reporting_marks": car.reporting_marks,
        "car_number": car.car_number,
        "car_type": car.car_type,
        "destination_name": wb.destination.name if wb and wb.destination else None,
    }


# ── Industries ────────────────────────────────────────────────────────────────

@app.get("/api/industries")
def list_industries(db: Session = Depends(get_db)):
    return [industry_to_dict(i) for i in db.query(Industry).all()]


@app.post("/api/industries", status_code=201)
def create_industry(data: IndustryCreate, db: Session = Depends(get_db)):
    ind = Industry(**data.model_dump())
    db.add(ind)
    db.commit()
    db.refresh(ind)
    return industry_to_dict(ind)


@app.put("/api/industries/{ind_id}")
def update_industry(ind_id: int, data: IndustryCreate, db: Session = Depends(get_db)):
    ind = db.get(Industry, ind_id)
    if not ind:
        raise HTTPException(404, "Industry not found")
    for field, value in data.model_dump().items():
        setattr(ind, field, value)
    db.commit()
    return industry_to_dict(ind)


@app.delete("/api/industries/{ind_id}", status_code=204)
def delete_industry(ind_id: int, db: Session = Depends(get_db)):
    ind = db.get(Industry, ind_id)
    if not ind:
        raise HTTPException(404, "Industry not found")
    db.query(Waybill).filter(Waybill.industry_id == ind_id, Waybill.car_id == None).delete(synchronize_session=False)
    db.delete(ind)
    db.commit()


class IndustrySuggestRequest(BaseModel):
    description: str


@app.post("/api/industries/suggest")
def suggest_industry_endpoint(data: IndustrySuggestRequest, db: Session = Depends(get_db)):
    if not get_provider().is_available():
        raise HTTPException(503, "No AI provider available — check your API key settings")
    existing = [r.name for r in db.query(Industry).all()]
    known_commodities = [r.commodity for r in db.query(CommodityCarTypeMap).all()]
    try:
        from vision import suggest_industry
        result = suggest_industry(data.description, existing, known_commodities)
    except Exception as e:
        raise HTTPException(500, str(e))
    return {
        "industry_role": result.get("industry_role", "consumer"),
        "inbound_commodities": result.get("inbound_commodities", result.get("commodities", "")),
        "inbound_car_types": result.get("inbound_car_types", result.get("accepted_car_types", "")),
        "outbound_commodities": result.get("outbound_commodities", ""),
        "outbound_car_types": result.get("outbound_car_types", ""),
    }


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


class CommoditySuggestRequest(BaseModel):
    commodity: str


@app.post("/api/commodity-car-type-map/suggest")
def suggest_commodity_endpoint(data: CommoditySuggestRequest, db: Session = Depends(get_db)):
    if not get_provider().is_available():
        raise HTTPException(503, "No AI provider available — check your API key settings")
    existing = {r.commodity: r.car_type for r in db.query(CommodityCarTypeMap).all()}
    try:
        from vision import suggest_commodity_car_type
        result = suggest_commodity_car_type(data.commodity, existing)
    except Exception as e:
        raise HTTPException(500, str(e))
    return {"car_type": result.get("car_type", "boxcar")}


# ── Car Types ────────────────────────────────────────────────────────────────

@app.get("/api/car-types")
def list_car_types(db: Session = Depends(get_db)):
    return [{"id": ct.id, "name": ct.name, "default_photo_path": ct.default_photo_path} for ct in db.query(CarType).order_by(CarType.name).all()]


@app.post("/api/car-types", status_code=201)
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


@app.put("/api/car-types/{ct_id}/default-image")
def set_car_type_default_image(ct_id: int, body: dict, db: Session = Depends(get_db)):
    ct = db.get(CarType, ct_id)
    if not ct:
        raise HTTPException(404)
    ct.default_photo_path = body.get("photo_path") or None
    db.commit()
    return {"ok": True}


@app.delete("/api/car-types/{ct_id}", status_code=204)
def delete_car_type(ct_id: int, db: Session = Depends(get_db)):
    ct = db.get(CarType, ct_id)
    if not ct:
        raise HTTPException(404)
    if db.query(Car).filter(Car.car_type == ct.name).first():
        raise HTTPException(409, f'Cars exist with type "{ct.name}" — reassign them first')
    db.delete(ct)
    db.commit()


# ── Automation ───────────────────────────────────────────────────────────────

_WILDCARD_TYPES = {"all", "any", ""}
_ALWAYS_EMPTY_RETURN_TYPES = {"tank car", "hopper", "covered hopper"}


def _car_type_matches(required: Optional[str], car_type: str) -> bool:
    if not required or required.lower() in _WILDCARD_TYPES:
        return True
    return required.lower() == car_type.lower()


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
        role = getattr(ind, "industry_role", "consumer")

        def parse_csv(s):
            return [t.strip() for t in (s or "").split(",") if t.strip()]

        def fallback_type(types):
            t = [x for x in types if x.lower() not in _WILDCARD_TYPES]
            return t[0] if t else None

        # Inbound fields: commodities + car types for receiving direction
        inbound_commodities = parse_csv(ind.commodities)
        inbound_raw_types   = parse_csv(ind.inbound_car_types or ind.accepted_car_types)
        inbound_fallback    = fallback_type(inbound_raw_types)

        # Outbound fields: commodities + car types for shipping direction
        # Fall back to inbound fields so existing single-direction data keeps working
        outbound_commodities = parse_csv(ind.outbound_commodities or ind.commodities)
        outbound_raw_types   = parse_csv(ind.outbound_car_types or ind.accepted_car_types)
        outbound_fallback    = fallback_type(outbound_raw_types)

        has_inbound  = role in ("consumer", "transload")
        has_outbound = role in ("producer", "transload")

        if not inbound_commodities and not outbound_commodities:
            continue

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

        # Inbound loaded waybills (staging → industry)
        if has_inbound:
            for commodity in inbound_commodities:
                req_type = commodity_map.get(commodity.lower(), inbound_fallback)
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

        # Outbound loaded waybills (industry → staging)
        if has_outbound:
            for commodity in outbound_commodities:
                req_type = commodity_map.get(commodity.lower(), outbound_fallback)
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

        # Empty return waybills (industry → staging), one per inbound car type
        inbound_empty_types = [ct for ct in inbound_raw_types if ct.lower() not in _WILDCARD_TYPES]
        if inbound_empty_types:
            for ct in inbound_empty_types:
                n = f"← {ind.name} (empty {ct})"
                if not _wb_exists(n):
                    _add(Waybill(name=n, origin_id=ind.location_id,
                        destination_id=data.origin_location_id, industry_id=ind.id,
                        commodity="", required_car_type=ct, is_empty=True))
                else:
                    skipped += 1
        elif has_inbound:
            n = f"← {ind.name} (empty)"
            if not _wb_exists(n):
                _add(Waybill(name=n, origin_id=ind.location_id,
                    destination_id=data.origin_location_id, industry_id=ind.id,
                    commodity="", required_car_type=None, is_empty=True))

        # Empty delivery waybills (staging → industry), one per outbound car type
        if has_outbound:
            outbound_empty_types = [ct for ct in outbound_raw_types if ct.lower() not in _WILDCARD_TYPES]
            if outbound_empty_types:
                for ct in outbound_empty_types:
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
                        commodity="", required_car_type=outbound_fallback, is_empty=True))

    db.commit()
    for w in new_waybills:
        db.refresh(w)
    return {"created": created, "skipped": skipped, "waybills": [waybill_to_dict(w) for w in new_waybills]}


def _clone_waybill(source, car, slot: int, db: Session):
    clone = Waybill(
        name=source.name,
        origin_id=source.origin_id,
        destination_id=source.destination_id,
        industry_id=source.industry_id,
        commodity=source.commodity,
        required_car_type=source.required_car_type,
        is_empty=source.is_empty,
        car_id=car.id,
        slot_index=slot,
    )
    db.add(clone)
    db.flush()
    return clone


def _fallback_candidate(db: Session, current_loc: int, staging_ids: set, car_type: str, always_empty: bool):
    """Search all waybills (including assigned) for a route to clone when the unassigned pool is exhausted."""
    if current_loc in staging_ids:
        candidates = db.query(Waybill).filter(
            Waybill.origin_id == current_loc,
            Waybill.is_empty == False,
            Waybill.destination_id.isnot(None),
        ).limit(20).all()
    elif always_empty:
        candidates = db.query(Waybill).filter(
            Waybill.origin_id == current_loc,
            Waybill.is_empty == True,
            Waybill.destination_id.in_(list(staging_ids)),
        ).limit(20).all()
    else:
        candidates = db.query(Waybill).filter(
            Waybill.origin_id == current_loc,
            Waybill.destination_id.isnot(None),
        ).limit(20).all()
    for w in candidates:
        if _car_type_matches(w.required_car_type, car_type):
            return w
    return None


def _fallback_starting_loc(db: Session, staging_ids: set, car_type: str):
    """When the unassigned pool has no staging-origin waybills, query all waybills for one to seed routing."""
    candidates = db.query(Waybill).filter(
        Waybill.origin_id.in_(list(staging_ids)),
        Waybill.is_empty == False,
        Waybill.destination_id.isnot(None),
    ).limit(20).all()
    for w in candidates:
        if _car_type_matches(w.required_car_type, car_type):
            return w.origin_id
    return None


def auto_assign_one_car(car, unassigned: list, staging_ids: set, db: Session, starting_loc=None) -> int:
    """Fill open waybill slots for a single car. Returns number of slots filled.
    Mutates `unassigned` in place (removes assigned loaded waybills).
    Falls back to cloning existing waybills when the pool is exhausted so all 4 slots are always filled."""
    occupied = {w.slot_index for w in car.waybills if w.slot_index is not None}
    open_slots = [s for s in range(4) if s not in occupied]
    if not open_slots:
        return 0

    always_empty = any(t in car.car_type.lower() for t in _ALWAYS_EMPTY_RETURN_TYPES)

    if not car.waybills:
        if starting_loc is not None:
            current_loc = starting_loc
        else:
            current_loc = _find_best_staging_for_car(unassigned, staging_ids, car.car_type, loaded_only=always_empty)
            if current_loc is None:
                current_loc = _fallback_starting_loc(db, staging_ids, car.car_type)
        if current_loc is None:
            return 0
    else:
        filled = sorted(w.slot_index for w in car.waybills if w.slot_index is not None)
        last = filled[-1]
        expected = list(range(last + 1, last + 1 + len(open_slots)))
        if open_slots != expected:
            return 0
        last_wb = next((w for w in car.waybills if w.slot_index == last), None)
        if last_wb is None or last_wb.destination_id is None:
            return 0
        current_loc = last_wb.destination_id

    assigned = 0
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
            candidate = _fallback_candidate(db, current_loc, staging_ids, car.car_type, always_empty)
            if candidate is None:
                break
            _clone_waybill(candidate, car, slot, db)
            assigned += 1
            current_loc = candidate.destination_id
            if current_loc is None:
                break
            continue

        if candidate.is_empty:
            _clone_waybill(candidate, car, slot, db)
        else:
            candidate.car_id = car.id
            candidate.slot_index = slot
            unassigned.remove(candidate)

        assigned += 1
        current_loc = candidate.destination_id
        if current_loc is None:
            break

    return assigned


def clear_car_slots(car, db: Session):
    """Unassign all waybill slots from a car, returning loaded waybills to the pool.
    Cloned empty waybills are deleted (they have no independent pool entry).
    Resets active_waybill_slot to 0 so the fresh assignment starts at the beginning."""
    for wb in list(car.waybills):
        if wb.is_empty:
            db.delete(wb)
        else:
            wb.car_id = None
            wb.slot_index = None
    car.active_waybill_slot = 0
    db.commit()


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
        assigned += auto_assign_one_car(car, unassigned, staging_ids, db)

    db.commit()
    for car in cars:
        db.refresh(car)
    return {"assigned": assigned, "cars_updated": [car_to_dict(c) for c in cars]}


@app.post("/api/cars/{car_id}/auto-assign")
def auto_assign_single_car(car_id: int, db: Session = Depends(get_db)):
    car = db.get(Car, car_id)
    if not car:
        raise HTTPException(404, "Car not found")
    clear_car_slots(car, db)
    db.refresh(car)
    staging_ids = {
        loc.id for loc in
        db.query(Location).filter(Location.location_type.in_(["staging", "yard"])).all()
    }
    unassigned = db.query(Waybill).filter(Waybill.car_id.is_(None)).all()
    assigned = auto_assign_one_car(car, unassigned, staging_ids, db, starting_loc=car.current_location_id)
    db.commit()
    db.refresh(car)
    return {"assigned": assigned, "car": car_to_dict(car)}


# ── Upload library ───────────────────────────────────────────────────────────

@app.get("/api/uploads")
def list_uploads(db: Session = Depends(get_db)):
    assigned = {car.photo_path for car in db.query(Car).all() if car.photo_path}
    for ct in db.query(CarType).all():
        if ct.default_photo_path:
            assigned.add(ct.default_photo_path)
    files = []
    for f in sorted(UPLOADS_DIR.iterdir(), key=lambda x: x.stat().st_mtime, reverse=True):
        if f.is_file() and f.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp", ".gif"):
            files.append({
                "path": str(f),
                "url": "/" + str(f),
                "assigned": str(f) in assigned,
                "is_default": False,
            })
    static_car_dir = Path("static/images/car-types")
    if static_car_dir.exists():
        for f in sorted(static_car_dir.iterdir(), key=lambda x: x.name):
            if f.is_file() and f.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp", ".gif", ".svg"):
                files.append({
                    "path": str(f),
                    "url": "/" + str(f),
                    "assigned": str(f) in assigned,
                    "is_default": True,
                })
    return files


@app.post("/api/uploads/purge")
def purge_uploads(db: Session = Depends(get_db)):
    assigned = {car.photo_path for car in db.query(Car).all() if car.photo_path}
    for ct in db.query(CarType).all():
        if ct.default_photo_path:
            assigned.add(ct.default_photo_path)
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


class DeleteUploadsRequest(BaseModel):
    paths: list[str]

@app.post("/api/uploads/delete-many", status_code=200)
def delete_uploads(data: DeleteUploadsRequest, db: Session = Depends(get_db)):
    assigned = {car.photo_path for car in db.query(Car).all() if car.photo_path}
    for ct in db.query(CarType).all():
        if ct.default_photo_path:
            assigned.add(ct.default_photo_path)
    uploads_resolved = UPLOADS_DIR.resolve()
    deleted = 0
    protected = 0
    for path_str in data.paths:
        target = Path(path_str).resolve()
        if not str(target).startswith(str(uploads_resolved)):
            continue
        if path_str in assigned:
            protected += 1
            continue
        target.unlink(missing_ok=True)
        deleted += 1
    return {"deleted": deleted, "protected": protected}


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
    storage_ids = {l.id for l in db.query(Location).filter(
        Location.location_type == "storage"
    ).all()}
    arrivals, departures, spots, warnings = [], [], [], []

    for car in db.query(Car).all():
        wb = _get_active_waybill(car)
        if not wb or wb.destination_id is None:
            continue
        if car.current_location_id != wb.destination_id:
            if car.current_location_id in dispatch_ids:
                arrivals.append(car)
            elif wb.destination_id in dispatch_ids:
                departures.append(car)
            elif car.current_location_id in storage_ids:
                spots.append(car)
            else:
                departures.append(car)

    arrivals   = sorted(arrivals,   key=lambda c: c.id)[:5]
    departures = sorted(departures, key=lambda c: c.id)[:min(5, max(len(arrivals), len(departures)))]
    spots      = sorted(spots,      key=lambda c: c.id)[:5]

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
        "spots":      [_enrich(c) for c in spots],
        "warnings":   warnings,
    }


# ── Layout settings ───────────────────────────────────────────────────────────

def _get_or_create_settings(db: Session) -> LayoutSettings:
    s = db.get(LayoutSettings, 1)
    if not s:
        s = LayoutSettings(id=1)
        db.add(s)
        db.commit()
        db.refresh(s)
    return s


def _settings_to_dict(s: LayoutSettings) -> dict:
    return {"clock_start_time": s.clock_start_time, "clock_speed": s.clock_speed}


@app.get("/api/settings")
def get_settings(db: Session = Depends(get_db)):
    return _settings_to_dict(_get_or_create_settings(db))


class LayoutSettingsUpdate(BaseModel):
    clock_start_time: str = "08:00"
    clock_speed: int = 4


@app.put("/api/settings")
def update_settings(data: LayoutSettingsUpdate, db: Session = Depends(get_db)):
    s = _get_or_create_settings(db)
    s.clock_start_time = data.clock_start_time
    s.clock_speed = data.clock_speed
    db.commit()
    return _settings_to_dict(s)


# ── Session clock ─────────────────────────────────────────────────────────────

def _clock_to_dict(c: SessionClock) -> dict:
    return {
        "started_at": c.started_at,
        "paused_at": c.paused_at,
        "paused_accum_s": c.paused_accum_s,
        "start_time": c.start_time,
        "speed": c.speed,
    }


def _start_session_clock(db: Session):
    s = _get_or_create_settings(db)
    c = db.get(SessionClock, 1)
    if not c:
        c = SessionClock(id=1)
        db.add(c)
    c.started_at = time.time()
    c.paused_at = None
    c.paused_accum_s = 0.0
    c.start_time = s.clock_start_time
    c.speed = s.clock_speed
    db.commit()


def _clear_session_clock(db: Session):
    c = db.get(SessionClock, 1)
    if c:
        db.delete(c)
        db.commit()


@app.get("/api/session/clock")
def get_session_clock(db: Session = Depends(get_db)):
    c = db.get(SessionClock, 1)
    if not c or c.started_at is None:
        return None
    return _clock_to_dict(c)


@app.post("/api/session/clock/pause")
def pause_session_clock(db: Session = Depends(get_db)):
    c = db.get(SessionClock, 1)
    if not c or c.paused_at is not None:
        return {"status": "already paused or no clock"}
    c.paused_at = time.time()
    db.commit()
    return _clock_to_dict(c)


@app.post("/api/session/clock/resume")
def resume_session_clock(db: Session = Depends(get_db)):
    c = db.get(SessionClock, 1)
    if not c or c.paused_at is None:
        return {"status": "not paused"}
    c.paused_accum_s += time.time() - c.paused_at
    c.paused_at = None
    db.commit()
    return _clock_to_dict(c)


@app.post("/api/session/clock/start")
def start_session_clock(db: Session = Depends(get_db)):
    _start_session_clock(db)
    c = db.get(SessionClock, 1)
    return _clock_to_dict(c)


# ── Session ───────────────────────────────────────────────────────────────────

@app.post("/api/session/plan")
def session_plan(db: Session = Depends(get_db)):
    plan = _build_session_plan(db)
    _start_session_clock(db)
    return plan


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
    _clear_session_clock(db)
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
        "switching_areas":        [_row_to_dict(r) for r in db.query(SwitchingArea).all()],
        "locations":              [_row_to_dict(r) for r in db.query(Location).all()],
        "industries":             [_row_to_dict(r) for r in db.query(Industry).all()],
        "commodity_car_type_map": [_row_to_dict(r) for r in db.query(CommodityCarTypeMap).all()],
        "cars":                   [_row_to_dict(r) for r in db.query(Car).all()],
        "waybills":               [_row_to_dict(r) for r in db.query(Waybill).all()],
        "movement_logs":          [_row_to_dict(r) for r in db.query(MovementLog).all()],
        "dispatch_plan":          [_row_to_dict(r) for r in db.query(DispatchPlan).all()],
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
    db.query(DispatchPlan).delete(synchronize_session=False)
    db.query(MovementLog).delete(synchronize_session=False)
    db.query(Waybill).delete(synchronize_session=False)
    db.query(Car).delete(synchronize_session=False)
    db.query(CommodityCarTypeMap).delete(synchronize_session=False)
    db.query(Industry).delete(synchronize_session=False)
    db.query(Location).delete(synchronize_session=False)
    db.query(SwitchingArea).delete(synchronize_session=False)
    db.flush()

    # Insert in FK order (SwitchingArea before Location)
    _import_table(db, SwitchingArea,       tables.get("switching_areas", []))
    _import_table(db, Location,            tables.get("locations", []))
    _import_table(db, Industry,            tables.get("industries", []))
    _import_table(db, CommodityCarTypeMap, tables.get("commodity_car_type_map", []))
    _import_table(db, Car,                 tables.get("cars", []))
    _import_table(db, Waybill,             tables.get("waybills", []))
    _import_table(db, MovementLog,         tables.get("movement_logs", []))
    _import_table(db, DispatchPlan,        tables.get("dispatch_plan", []))
    db.commit()
    return {"ok": True}


@app.post("/api/import/cars")
async def import_cars(
    file: UploadFile = File(...),
    mode: str = "add",
    dry_run: str = "false",
    db: Session = Depends(get_db),
):
    content = (await file.read()).decode("utf-8", errors="replace")
    filename = (file.filename or "").lower()

    if filename.endswith(".xml"):
        parsed, errors = parse_jmri_cars(content)
    else:
        parsed, errors = parse_csv_cars(content)

    is_dry = dry_run.lower() == "true"
    skipped_duplicates = 0
    valid = []

    existing_keys = {
        (c.reporting_marks.lower(), c.car_number.lower())
        for c in db.query(Car).all()
    }

    for row in parsed:
        key = (row["reporting_marks"].lower(), row["car_number"].lower())
        if mode == "add" and key in existing_keys:
            skipped_duplicates += 1
        else:
            valid.append(row)

    if not is_dry:
        if mode == "replace":
            db.query(MovementLog).delete()
            db.query(Waybill).filter(Waybill.car_id.isnot(None)).delete()
            db.query(Car).delete()
            db.flush()
        for row in valid:
            db.add(Car(
                reporting_marks=row["reporting_marks"],
                car_number=row["car_number"],
                car_type=row["car_type"],
                color=row["color"],
            ))
        db.commit()

    return {
        "rows": valid,          # all valid rows for the frontend to store
        "preview": valid[:8],   # first 8 for display
        "total": len(valid),
        "skipped_duplicates": skipped_duplicates,
        "errors": errors,
    }


@app.post("/api/import/cars/commit")
def commit_car_import(data: CarImportCommit, db: Session = Depends(get_db)):
    if data.mode == "replace":
        db.query(MovementLog).delete()
        db.query(Waybill).filter(Waybill.car_id.isnot(None)).delete()
        db.query(Car).delete()
        db.flush()

    existing_keys = {
        (c.reporting_marks.lower(), c.car_number.lower())
        for c in db.query(Car).all()
    }
    imported = 0
    for row in data.cars:
        key = (row.reporting_marks.lower(), row.car_number.lower())
        if data.mode == "add" and key in existing_keys:
            continue
        db.add(Car(
            reporting_marks=row.reporting_marks,
            car_number=row.car_number,
            car_type=row.car_type,
            color=row.color,
        ))
        imported += 1
    db.commit()
    return {"imported": imported}
