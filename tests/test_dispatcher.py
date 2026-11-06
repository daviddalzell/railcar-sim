# SPDX-FileCopyrightText: 2026 David Dalzell
# SPDX-License-Identifier: MIT

"""Dispatcher build-algorithm tests: per-track capacity, industry spot
capacity, destination-mismatch warnings, warning persistence, and the
preview (dry-run) endpoints."""

import pytest
from fastapi.testclient import TestClient

from auth import get_current_user
from database import get_db
from main import app
from models import Location
from tests.conftest import make_car, make_industry, make_location, make_waybill

_ADMIN = {"id": "adm1", "email": "admin@test.com", "role": "admin"}


@pytest.fixture()
def admin_client(db_session):
    app.dependency_overrides[get_db] = lambda: db_session
    app.dependency_overrides[get_current_user] = lambda: _ADMIN
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def test_build_plan_still_delivers_cars_over_track_capacity(admin_client, db_session):
    """A full siding doesn't refuse the car — it rides along for CP since the area has room."""
    area = Location(name="Industrial Park", car_capacity=20)
    db_session.add(area)
    db_session.flush()
    origin = make_location(db_session, "Staging", "staging")
    dest = make_location(db_session, "Yard", "yard")
    track_a = make_location(db_session, "Track A", "industry")
    track_a.location_id = area.id
    track_a.car_capacity = 1
    db_session.flush()

    car1 = make_car(db_session, "boxcar", origin.id)
    car2 = make_car(db_session, "boxcar", origin.id)
    make_waybill(db_session, origin.id, track_a.id, car_id=car1.id, slot_index=0)
    make_waybill(db_session, origin.id, track_a.id, car_id=car2.id, slot_index=0)
    db_session.commit()

    r = admin_client.post("/api/dispatcher/build-plan", json={
        "origin_location_id": origin.id,
        "location_id": area.id,
        "destination_location_id": dest.id,
    })
    assert r.status_code == 200
    data = r.json()
    assert len(data["setouts"]) == 2  # neither car is excluded
    assert any("Track A" in w and "CP" in w for w in data["warnings"])


def test_build_plan_nets_out_same_visit_pulls(admin_client, db_session):
    """A siding occupant leaving this same trip frees its slot for an inbound car."""
    area = Location(name="Industrial Park", car_capacity=20)
    db_session.add(area)
    db_session.flush()
    origin = make_location(db_session, "Staging", "staging")
    dest = make_location(db_session, "Yard", "yard")
    track_a = make_location(db_session, "Track A", "industry")
    track_a.location_id = area.id
    track_a.car_capacity = 1
    db_session.flush()

    # Already occupies Track A, but is leaving this same trip (destination is the yard).
    leaving_car = make_car(db_session, "boxcar", track_a.id)
    make_waybill(db_session, track_a.id, dest.id, car_id=leaving_car.id, slot_index=0)
    # New arrival destined for Track A, from the origin.
    arriving_car = make_car(db_session, "boxcar", origin.id)
    make_waybill(db_session, origin.id, track_a.id, car_id=arriving_car.id, slot_index=0)
    db_session.commit()

    r = admin_client.post("/api/dispatcher/build-plan", json={
        "origin_location_id": origin.id,
        "location_id": area.id,
        "destination_location_id": dest.id,
    })
    assert r.status_code == 200
    data = r.json()
    assert len(data["setouts"]) == 1
    assert len(data["pickups"]) == 1
    assert not any("Track A" in w for w in data["warnings"])


def test_build_plan_warns_on_industry_overcapacity(admin_client, db_session):
    area = Location(name="Downtown", car_capacity=20)
    db_session.add(area)
    db_session.flush()
    origin = make_location(db_session, "Staging", "staging")
    dest = make_location(db_session, "Yard", "yard")
    industry_track = make_location(db_session, "Mill Spur", "industry")
    industry_track.location_id = area.id
    db_session.flush()
    industry = make_industry(db_session, "Acme Mill", industry_track.id)
    industry.spot_numbers = "1"
    db_session.flush()

    car1 = make_car(db_session, "boxcar", origin.id)
    car2 = make_car(db_session, "boxcar", origin.id)
    make_waybill(db_session, origin.id, industry_track.id, industry_id=industry.id, car_id=car1.id, slot_index=0)
    make_waybill(db_session, origin.id, industry_track.id, industry_id=industry.id, car_id=car2.id, slot_index=0)
    db_session.commit()

    r = admin_client.post("/api/dispatcher/build-plan", json={
        "origin_location_id": origin.id,
        "location_id": area.id,
        "destination_location_id": dest.id,
    })
    assert r.status_code == 200
    data = r.json()
    assert len(data["setouts"]) == 2  # industry capacity only warns — it doesn't truncate
    assert any("Acme Mill" in w and "CP" in w for w in data["warnings"])


def test_build_plan_warns_on_destination_mismatch(admin_client, db_session):
    area = Location(name="Downtown", car_capacity=20)
    db_session.add(area)
    db_session.flush()
    origin = make_location(db_session, "Staging", "staging")
    chosen_dest = make_location(db_session, "North Yard", "yard")
    other_dest = make_location(db_session, "South Yard", "yard")
    track_in_area = make_location(db_session, "Siding 1", "yard")
    track_in_area.location_id = area.id
    db_session.flush()

    car = make_car(db_session, "boxcar", track_in_area.id)
    make_waybill(db_session, track_in_area.id, other_dest.id, car_id=car.id, slot_index=0)
    db_session.commit()

    r = admin_client.post("/api/dispatcher/build-plan", json={
        "origin_location_id": origin.id,
        "location_id": area.id,
        "destination_location_id": chosen_dest.id,
    })
    assert r.status_code == 200
    data = r.json()
    assert len(data["pickups"]) == 1  # still included — broad matching is unchanged, just warned about
    assert any("North Yard" in w for w in data["warnings"])


def test_dispatch_plan_warnings_persist_across_get(admin_client, db_session):
    area = Location(name="Industrial Park", car_capacity=20)
    db_session.add(area)
    db_session.flush()
    origin = make_location(db_session, "Staging", "staging")
    dest = make_location(db_session, "Yard", "yard")
    track_a = make_location(db_session, "Track A", "industry")
    track_a.location_id = area.id
    track_a.car_capacity = 1
    db_session.flush()

    car1 = make_car(db_session, "boxcar", origin.id)
    car2 = make_car(db_session, "boxcar", origin.id)
    make_waybill(db_session, origin.id, track_a.id, car_id=car1.id, slot_index=0)
    make_waybill(db_session, origin.id, track_a.id, car_id=car2.id, slot_index=0)
    db_session.commit()

    built = admin_client.post("/api/dispatcher/build-plan", json={
        "origin_location_id": origin.id,
        "location_id": area.id,
        "destination_location_id": dest.id,
    }).json()
    assert built["warnings"]
    plan_id = built["id"]

    listed = admin_client.get("/api/dispatcher/plans").json()
    fetched = admin_client.get(f"/api/dispatcher/plan/{plan_id}").json()
    assert listed[0]["warnings"] == built["warnings"]
    assert fetched["warnings"] == built["warnings"]


def test_preview_plan_does_not_persist(admin_client, db_session):
    from models import DispatchPlan

    area = Location(name="Yard", car_capacity=10)
    db_session.add(area)
    db_session.flush()
    origin = make_location(db_session, "Staging", "staging")
    dest = make_location(db_session, "Yard2", "yard")
    db_session.commit()

    r = admin_client.post("/api/dispatcher/preview-plan", json={
        "origin_location_id": origin.id,
        "location_id": area.id,
        "destination_location_id": dest.id,
    })
    assert r.status_code == 200
    body = r.json()
    assert set(["inbound", "outbound", "local_spots", "available_spots", "warnings"]) <= body.keys()
    assert db_session.query(DispatchPlan).count() == 0


def test_preview_rebuild_matches_plans_origin_area_destination(admin_client, db_session):
    area = Location(name="Yard", car_capacity=10)
    db_session.add(area)
    db_session.flush()
    origin = make_location(db_session, "Staging", "staging")
    dest = make_location(db_session, "Yard2", "yard")
    track = make_location(db_session, "Siding", "yard")
    track.location_id = area.id
    db_session.flush()

    car = make_car(db_session, "boxcar", origin.id)
    make_waybill(db_session, origin.id, track.id, car_id=car.id, slot_index=0)
    db_session.commit()

    built = admin_client.post("/api/dispatcher/build-plan", json={
        "origin_location_id": origin.id,
        "location_id": area.id,
        "destination_location_id": dest.id,
    }).json()
    assert len(built["setouts"]) == 1

    preview = admin_client.post(f"/api/dispatcher/plan/{built['id']}/preview-rebuild")
    assert preview.status_code == 200
    assert len(preview.json()["inbound"]) == 1
    assert preview.json()["inbound"][0]["id"] == car.id
