# SPDX-FileCopyrightText: 2026 David Dalzell
# SPDX-License-Identifier: AGPL-3.0-or-later

from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

import storage
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
    for item in storage.list_uploaded_files():
        files.append({
            "path": item["path"],
            "url": item["url"],
            "assigned": item["path"] in assigned,
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
    for item in storage.list_uploaded_files():
        if item["path"] not in assigned:
            storage.delete(item["path"])
            deleted += 1
    return {"deleted": deleted}


@router.post("/uploads/delete", status_code=204)
def delete_upload(data: DeleteUploadRequest):
    path = data.path
    # Safety check: only allow deleting stylized images via this endpoint
    filename = path.split("/")[-1]
    if not filename.endswith("_stylized.png"):
        raise HTTPException(400, "Only stylized images may be deleted this way")
    storage.delete(path)


@router.post("/uploads/delete-many", status_code=200)
def delete_uploads(data: DeleteUploadsRequest, db: Session = Depends(get_db)):
    assigned = {car.photo_path for car in db.query(Car).all() if car.photo_path}
    for ct in db.query(CarType).all():
        if ct.default_photo_path:
            assigned.add(ct.default_photo_path)
    deleted = 0
    protected = 0
    for path_str in data.paths:
        if path_str in assigned:
            protected += 1
            continue
        storage.delete(path_str)
        deleted += 1
    return {"deleted": deleted, "protected": protected}
