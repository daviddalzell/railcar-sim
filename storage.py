# SPDX-FileCopyrightText: 2026 David Dalzell
# SPDX-License-Identifier: MIT

"""Storage abstraction: Supabase Storage (cloud) or local uploads/ directory (local dev).

All public functions return/accept a `photo_path` value that is stored in the DB:
- Local:    relative path  e.g. "uploads/abc123.jpg"
- Supabase: full CDN URL   e.g. "https://xxx.supabase.co/storage/v1/object/public/uploads/abc123.jpg"

Callers distinguish the two by checking whether the value starts with "http".
"""
import os
from pathlib import Path

UPLOADS_DIR = Path("uploads")
_BUCKET = "uploads"

_supabase_client = None


def _get_client():
    global _supabase_client
    if _supabase_client is None:
        from supabase import create_client
        _supabase_client = create_client(
            os.environ["SUPABASE_URL"],
            os.environ["SUPABASE_KEY"],
        )
    return _supabase_client


def _using_supabase() -> bool:
    return bool(os.environ.get("SUPABASE_URL"))


# ── Public API ────────────────────────────────────────────────────────────────

def upload(filename: str, data: bytes, content_type: str = "image/jpeg") -> str:
    """Store a file and return the photo_path value to persist in the DB."""
    if _using_supabase():
        client = _get_client()
        storage_path = f"uploads/{filename}"
        client.storage.from_(_BUCKET).upload(
            storage_path, data, {"content-type": content_type, "upsert": "true"}
        )
        return client.storage.from_(_BUCKET).get_public_url(storage_path)
    else:
        UPLOADS_DIR.mkdir(exist_ok=True)
        dest = UPLOADS_DIR / filename
        dest.write_bytes(data)
        return str(dest)


def delete(photo_path: str):
    """Delete a stored file. photo_path is the value from the DB."""
    if not photo_path:
        return
    if _using_supabase() and photo_path.startswith("http"):
        client = _get_client()
        # Extract the storage path from the CDN URL
        # URL format: .../object/public/<bucket>/<path>
        marker = f"/object/public/{_BUCKET}/"
        idx = photo_path.find(marker)
        if idx != -1:
            storage_path = f"uploads/{photo_path[idx + len(marker):]}"
            client.storage.from_(_BUCKET).remove([storage_path])
    else:
        Path(photo_path).unlink(missing_ok=True)


def read_bytes(photo_path: str) -> bytes:
    """Read a stored file as bytes, regardless of backend."""
    if photo_path.startswith("http"):
        import urllib.request
        with urllib.request.urlopen(photo_path) as resp:  # noqa: S310 — internal CDN URL
            return resp.read()
    return Path(photo_path).read_bytes()


def photo_url(photo_path: str) -> str:
    """Return the public URL for a photo_path DB value."""
    if not photo_path:
        return ""
    if photo_path.startswith("http"):
        return photo_path          # already a full CDN URL
    return "/" + photo_path.replace("\\", "/")   # local: prepend /


def list_uploaded_files() -> list[dict]:
    """List user-uploaded files (not static defaults). Returns [{path, url}]."""
    if _using_supabase():
        client = _get_client()
        try:
            items = client.storage.from_(_BUCKET).list("uploads")
        except Exception:
            return []
        result = []
        for item in items:
            if not item.get("name"):
                continue
            storage_path = f"uploads/{item['name']}"
            url = client.storage.from_(_BUCKET).get_public_url(storage_path)
            result.append({"path": url, "url": url})
        return result
    else:
        UPLOADS_DIR.mkdir(exist_ok=True)
        result = []
        _img_exts = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
        for f in sorted(UPLOADS_DIR.iterdir(), key=lambda x: x.stat().st_mtime, reverse=True):
            if f.is_file() and f.suffix.lower() in _img_exts:
                result.append({"path": str(f), "url": "/" + str(f)})
        return result
