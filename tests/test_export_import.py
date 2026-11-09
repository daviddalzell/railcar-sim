# SPDX-FileCopyrightText: 2026 David Dalzell
# SPDX-License-Identifier: MIT

"""ZIP backup import (`/api/import`), including backward compatibility with
older backup formats (issue #66)."""

import io
import json
import zipfile


def _zip_payload(tables: dict) -> bytes:
    payload = {"version": 1, "exported_at": "2026-01-01T00:00:00", "tables": tables}
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("data.json", json.dumps(payload))
    return buf.getvalue()


def test_import_old_format_remaps_switching_area_id_to_location_id(client):
    """Pre-rename backups named the Track model's group FK `switching_area_id`;
    the current Track model column is `location_id`. Without remapping it,
    import_table's column-key filter silently drops it and every imported
    track comes in unassigned (issue #66)."""
    old_format = _zip_payload({
        "switching_areas": [{"id": 1, "name": "Moline Alley", "car_capacity": 8}],
        "locations": [
            {"id": 5, "name": "SPNS 1201", "location_type": "industry",
             "switching_area_id": 1, "car_capacity": 2},
            {"id": 9, "name": "Cornfield", "location_type": "staging",
             "switching_area_id": None, "car_capacity": None},
        ],
    })
    r = client.post("/api/import", files={"file": ("backup.zip", old_format, "application/zip")})
    assert r.status_code == 200

    groups = client.get("/api/locations").json()
    assert len(groups) == 1
    assert groups[0]["name"] == "Moline Alley"

    tracks = {t["name"]: t for t in client.get("/api/tracks").json()}
    assert tracks["SPNS 1201"]["location_id"] == groups[0]["id"]
    assert tracks["Cornfield"]["location_id"] is None


def test_import_new_format_unaffected(client):
    """The current backup format ("locations" + "tracks") needs no remap —
    confirm the old-format fix didn't disturb it."""
    new_format = _zip_payload({
        "locations": [{"id": 1, "name": "Moline Alley", "car_capacity": 8}],
        "tracks": [{"id": 5, "name": "SPNS 1201", "location_type": "industry",
                    "location_id": 1, "car_capacity": 2}],
    })
    r = client.post("/api/import", files={"file": ("backup.zip", new_format, "application/zip")})
    assert r.status_code == 200

    tracks = client.get("/api/tracks").json()
    assert len(tracks) == 1
    assert tracks[0]["location_id"] == 1
