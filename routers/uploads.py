from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from database import get_db
from models import Car, CarType
from schemas import DeleteUploadRequest, DeleteUploadsRequest

UPLOADS_DIR = Path("uploads")

router = APIRouter(prefix="/api", tags=["uploads"])


@router.get("/uploads")
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


@router.post("/uploads/purge")
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


@router.post("/uploads/delete", status_code=204)
def delete_upload(data: DeleteUploadRequest):
    target = Path(data.path).resolve()
    uploads_resolved = UPLOADS_DIR.resolve()
    if not str(target).startswith(str(uploads_resolved)):
        raise HTTPException(400, "Path outside uploads directory")
    if not target.name.endswith("_stylized.png"):
        raise HTTPException(400, "Only stylized images may be deleted this way")
    target.unlink(missing_ok=True)


@router.post("/uploads/delete-many", status_code=200)
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
