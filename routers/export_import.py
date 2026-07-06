# SPDX-FileCopyrightText: 2026 David Dalzell
# SPDX-License-Identifier: MIT

import csv
import io
import json
import xml.etree.ElementTree as ET
import zipfile
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy import DateTime as SADateTime
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.orm import Session
from starlette.requests import Request

from database import get_db
from models import Car, CarType, CommodityCarTypeMap, DispatchPlan, Industry, Location, MovementLog, SwitchingArea, Waybill
from converters import row_to_dict
from schemas import CarImportCommit

UPLOADS_DIR = Path("uploads")

router = APIRouter(prefix="/api", tags=["export_import"])


# ── Export / Import table helper ─────────────────────────────────────────────

def import_table(db: Session, model, rows: list) -> None:
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


# ── Routes ────────────────────────────────────────────────────────────────────

@router.get("/export")
def export_data(db: Session = Depends(get_db)):
    import urllib.request
    from datetime import date as _date
    tables = {
        "switching_areas":        [row_to_dict(r) for r in db.query(SwitchingArea).all()],
        "locations":              [row_to_dict(r) for r in db.query(Location).all()],
        "industries":             [row_to_dict(r) for r in db.query(Industry).all()],
        "commodity_car_type_map": [row_to_dict(r) for r in db.query(CommodityCarTypeMap).all()],
        "cars":                   [row_to_dict(r) for r in db.query(Car).all()],
        "waybills":               [row_to_dict(r) for r in db.query(Waybill).all()],
        "movement_logs":          [row_to_dict(r) for r in db.query(MovementLog).all()],
        "dispatch_plan":          [row_to_dict(r) for r in db.query(DispatchPlan).all()],
    }
    payload = {"version": 1, "exported_at": datetime.utcnow().isoformat(), "tables": tables}
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("data.json", json.dumps(payload, indent=2))
        for car_row in tables["cars"]:
            photo = car_row.get("photo_path") or ""
            if not photo:
                continue
            fname = Path(photo.split("?")[0]).name
            if photo.startswith("http"):
                try:
                    with urllib.request.urlopen(photo) as resp:  # noqa: S310
                        zf.writestr(f"photos/{fname}", resp.read())
                except Exception:
                    pass
            elif Path(photo).exists():
                zf.write(photo, arcname=f"photos/{fname}")
    buf.seek(0)
    filename = f"railcar-backup-{_date.today().isoformat()}.zip"
    return StreamingResponse(buf, media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@router.post("/import")
async def import_data(request: Request, file: UploadFile = File(...), db: Session = Depends(get_db)):
    import storage as _storage
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

    # Re-upload photos into the current tenant's storage and build a remap table
    tenant = getattr(request.state, "tenant", None)
    folder = getattr(tenant, "schema_name", None) or "uploads"
    photo_remap: dict[str, str] = {}  # original filename -> new photo_path
    photo_errors: list[str] = []
    for name in zf.namelist():
        if name.startswith("photos/") and name != "photos/":
            fname = Path(name).name
            try:
                new_path = _storage.upload(fname, zf.read(name), "image/jpeg", folder=folder)
                photo_remap[fname] = new_path
            except Exception as exc:
                photo_errors.append(f"{fname}: {exc}")

    # Remap photo_path values in car rows to the newly uploaded locations
    for car_row in tables.get("cars", []):
        old = car_row.get("photo_path") or ""
        if old:
            old_fname = Path(old.split("?")[0]).name
            if old_fname in photo_remap:
                car_row["photo_path"] = photo_remap[old_fname]
            elif old_fname not in photo_remap and any(old_fname in e for e in photo_errors):
                car_row["photo_path"] = ""  # upload failed — clear rather than keep broken path

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
    import_table(db, SwitchingArea,       tables.get("switching_areas", []))
    import_table(db, Location,            tables.get("locations", []))
    import_table(db, Industry,            tables.get("industries", []))
    import_table(db, CommodityCarTypeMap, tables.get("commodity_car_type_map", []))
    import_table(db, Car,                 tables.get("cars", []))
    import_table(db, Waybill,            tables.get("waybills", []))
    import_table(db, MovementLog,         tables.get("movement_logs", []))
    import_table(db, DispatchPlan,        tables.get("dispatch_plan", []))
    db.commit()
    result: dict = {"ok": True, "photos_imported": len(photo_remap)}
    if photo_errors:
        result["photo_errors"] = photo_errors
    return result


@router.post("/import/cars")
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


@router.post("/import/cars/commit")
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
