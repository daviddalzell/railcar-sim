# SPDX-FileCopyrightText: 2026 David Dalzell
# SPDX-License-Identifier: MIT

"""API contract tests for the Location/Track rename (PR 2).

Guards the risky parts of the rename: the renamed `location_id` field on
tracks, the Location-group CRUD on `/api/locations`, the response-shape
changes in converters, and the removal of the old backward-compat aliases.
"""

from models import Industry, Location, Track
from tests.conftest import make_car, make_location, make_waybill


# ── Track CRUD uses the renamed location_id field ───────────────────────────────

def test_create_track_with_location_id(client, db_session):
    group = Location(name="Yard Complex", car_capacity=20)
    db_session.add(group)
    db_session.flush()

    r = client.post("/api/tracks", json={
        "name": "Siding 1",
        "location_type": "yard",
        "location_id": group.id,
        "car_capacity": 5,
    })
    assert r.status_code == 201
    body = r.json()
    assert body["name"] == "Siding 1"
    assert body["location_id"] == group.id
    assert body["car_capacity"] == 5
    # Old backward-compat key must be gone
    assert "switching_area_id" not in body


def test_create_track_without_group(client):
    r = client.post("/api/tracks", json={"name": "Lonely Track", "location_type": "staging"})
    assert r.status_code == 201
    assert r.json()["location_id"] is None


def test_update_track_reassigns_group(client, db_session):
    group_a = Location(name="Yard A", car_capacity=10)
    group_b = Location(name="Yard B", car_capacity=10)
    db_session.add_all([group_a, group_b])
    db_session.flush()
    track = Track(name="Siding", location_type="yard", location_id=group_a.id)
    db_session.add(track)
    db_session.flush()

    r = client.put(f"/api/tracks/{track.id}", json={
        "name": "Siding",
        "location_type": "yard",
        "location_id": group_b.id,
    })
    assert r.status_code == 200
    assert r.json()["location_id"] == group_b.id


def test_list_tracks_shape(client, db_session):
    make_location(db_session, "Yard", "yard")
    db_session.commit()
    r = client.get("/api/tracks")
    assert r.status_code == 200
    row = r.json()[0]
    assert set(row.keys()) == {"id", "name", "location_type", "location_id", "car_capacity", "current_car_count", "position"}


def test_track_current_car_count_reflects_cars_there(client, db_session):
    """Issue #46: the Layout Setup tree shows a per-track car-count chip,
    same as the Location-group chip already did."""
    track = make_location(db_session, "Siding 1", "industry")
    other = make_location(db_session, "Siding 2", "industry")
    make_car(db_session, "boxcar", track.id)
    make_car(db_session, "boxcar", track.id)
    make_car(db_session, "boxcar", other.id)
    db_session.commit()

    rows = {t["name"]: t for t in client.get("/api/tracks").json()}
    assert rows["Siding 1"]["current_car_count"] == 2
    assert rows["Siding 2"]["current_car_count"] == 1


# ── Location-group CRUD on /api/locations ───────────────────────────────────────

def test_create_location_group(client):
    r = client.post("/api/locations", json={"name": "Millbrook Yard", "car_capacity": 20})
    assert r.status_code == 201
    body = r.json()
    assert body["name"] == "Millbrook Yard"
    assert body["car_capacity"] == 20
    assert body["tracks"] == []
    # Old backward-compat key must be gone
    assert "locations" not in body


def test_location_group_lists_its_tracks(client, db_session):
    group = Location(name="Yard Complex", car_capacity=20)
    db_session.add(group)
    db_session.flush()
    db_session.add(Track(name="Siding 1", location_type="yard", location_id=group.id))
    db_session.add(Track(name="Siding 2", location_type="industry", location_id=group.id))
    db_session.commit()

    r = client.get("/api/locations")
    assert r.status_code == 200
    body = r.json()[0]
    assert "tracks" in body
    assert {t["name"] for t in body["tracks"]} == {"Siding 1", "Siding 2"}


def test_update_location_group(client, db_session):
    group = Location(name="Old Name", car_capacity=10)
    db_session.add(group)
    db_session.flush()

    r = client.put(f"/api/locations/{group.id}", json={"name": "New Name", "car_capacity": 30})
    assert r.status_code == 200
    assert r.json()["name"] == "New Name"
    assert r.json()["car_capacity"] == 30


def test_delete_location_group_ungroups_tracks_not_deletes_them(client, db_session):
    """Deleting a Location group must detach its tracks (location_id=None), not delete them."""
    group = Location(name="Yard Complex", car_capacity=20)
    db_session.add(group)
    db_session.flush()
    track = Track(name="Siding 1", location_type="yard", location_id=group.id)
    db_session.add(track)
    db_session.commit()
    track_id = track.id

    r = client.delete(f"/api/locations/{group.id}")
    assert r.status_code == 204

    db_session.expire_all()
    surviving = db_session.get(Track, track_id)
    assert surviving is not None, "track must survive its group's deletion"
    assert surviving.location_id is None, "track must be ungrouped"


# ── Backward-compat aliases are gone ────────────────────────────────────────────

def test_old_switching_areas_alias_removed(client):
    assert client.get("/api/switching-areas").status_code == 404
    assert client.post("/api/switching-areas", json={"name": "x"}).status_code == 404


# ── layout-status response shape ────────────────────────────────────────────────

def test_layout_status_uses_locations_key(client, db_session):
    group = Location(name="Yard Complex", car_capacity=20)
    db_session.add(group)
    db_session.flush()
    db_session.add(Track(name="Siding 1", location_type="yard", location_id=group.id))
    db_session.commit()

    r = client.get("/api/layout-status")
    assert r.status_code == 200
    body = r.json()
    assert "locations" in body
    assert "switching_areas" not in body


# ── Dispatcher build-plan happy path (exercises renamed location_id) ─────────────

def test_admin_can_build_dispatch_plan_with_location_id(client, db_session):
    group = Location(name="Switch District", car_capacity=20)
    db_session.add(group)
    db_session.flush()
    origin = Track(name="Staging", location_type="staging", location_id=group.id)
    dest = Track(name="Yard", location_type="yard", location_id=group.id)
    db_session.add_all([origin, dest])
    db_session.commit()

    r = client.post("/api/dispatcher/build-plan", json={
        "origin_location_id": origin.id,
        "location_id": group.id,
        "destination_location_id": dest.id,
    })
    assert r.status_code == 200
    body = r.json()
    assert body["location_id"] == group.id
    assert body["location_name"] == "Switch District"
    assert body["origin_location_id"] == origin.id
    assert body["destination_location_id"] == dest.id


def test_build_dispatch_plan_unknown_group_404(client, db_session):
    origin = make_location(db_session, "Staging", "staging")
    dest = make_location(db_session, "Yard", "yard")
    db_session.commit()

    r = client.post("/api/dispatcher/build-plan", json={
        "origin_location_id": origin.id,
        "location_id": 99999,
        "destination_location_id": dest.id,
    })
    assert r.status_code == 404
