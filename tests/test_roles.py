# SPDX-FileCopyrightText: 2026 David Dalzell
# SPDX-License-Identifier: MIT

"""Role-based access control tests.

Verifies that operator-role users are blocked from admin-only endpoints
and allowed through operator-permitted endpoints.
"""

import pytest
from fastapi.testclient import TestClient

from auth import get_current_user
from database import get_db
from main import app
from tests.conftest import make_car, make_location, make_industry


_OPERATOR = {"id": "op1", "email": "operator@test.com", "role": "operator"}
_ADMIN    = {"id": "adm1", "email": "admin@test.com",    "role": "admin"}


@pytest.fixture()
def operator_client(db_session):
    app.dependency_overrides[get_db] = lambda: db_session
    app.dependency_overrides[get_current_user] = lambda: _OPERATOR
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture()
def admin_client(db_session):
    app.dependency_overrides[get_db] = lambda: db_session
    app.dependency_overrides[get_current_user] = lambda: _ADMIN
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


# ── Locations: operators read-only ────────────────────────────────────────────

def test_operator_can_list_locations(operator_client):
    r = operator_client.get("/api/locations")
    assert r.status_code == 200


def test_operator_cannot_create_location(operator_client):
    r = operator_client.post("/api/locations", json={"name": "Yard", "location_type": "yard"})
    assert r.status_code == 403


def test_operator_cannot_update_location(operator_client, db_session):
    loc = make_location(db_session, "Yard", "yard")
    r = operator_client.put(f"/api/locations/{loc.id}", json={"name": "Yard2", "location_type": "yard"})
    assert r.status_code == 403


def test_operator_cannot_delete_location(operator_client, db_session):
    loc = make_location(db_session, "Staging A", "staging")
    r = operator_client.delete(f"/api/locations/{loc.id}")
    assert r.status_code == 403


def test_admin_can_create_location(admin_client):
    r = admin_client.post("/api/locations", json={"name": "Yard", "location_type": "yard"})
    assert r.status_code == 201


# ── Switching areas: operators read-only ─────────────────────────────────────

def test_operator_can_list_switching_areas(operator_client):
    r = operator_client.get("/api/switching-areas")
    assert r.status_code == 200


def test_operator_cannot_create_switching_area(operator_client):
    r = operator_client.post("/api/switching-areas", json={"name": "Main Yard", "car_capacity": 20})
    assert r.status_code == 403


def test_operator_cannot_delete_switching_area(operator_client, db_session):
    from models import SwitchingArea
    area = SwitchingArea(name="Test Yard", car_capacity=10)
    db_session.add(area)
    db_session.flush()
    r = operator_client.delete(f"/api/switching-areas/{area.id}")
    assert r.status_code == 403


# ── Industries: operators read-only ──────────────────────────────────────────

def test_operator_can_list_industries(operator_client):
    r = operator_client.get("/api/industries")
    assert r.status_code == 200


def test_operator_cannot_create_industry(operator_client, db_session):
    loc = make_location(db_session, "Grain Elevator", "industry")
    r = operator_client.post("/api/industries", json={
        "name": "Grain Co.", "location_id": loc.id,
        "industry_role": "consumer", "accepted_car_types": "covered hopper",
        "commodities": "grain", "inbound_car_types": "covered hopper",
        "outbound_commodities": "", "outbound_car_types": "", "spot_numbers": "",
    })
    assert r.status_code == 403


def test_operator_cannot_update_industry(operator_client, db_session):
    loc = make_location(db_session, "Fuel Depot", "industry")
    ind = make_industry(db_session, "Fuel Co.", loc.id)
    r = operator_client.put(f"/api/industries/{ind.id}", json={
        "name": "Fuel Co. 2", "location_id": loc.id,
        "industry_role": "consumer", "accepted_car_types": "tank car",
        "commodities": "fuel", "inbound_car_types": "tank car",
        "outbound_commodities": "", "outbound_car_types": "", "spot_numbers": "",
    })
    assert r.status_code == 403


def test_operator_cannot_delete_industry(operator_client, db_session):
    loc = make_location(db_session, "Lumber Mill", "industry")
    ind = make_industry(db_session, "Lumber Co.", loc.id)
    r = operator_client.delete(f"/api/industries/{ind.id}")
    assert r.status_code == 403


# ── Cars: operators can add/edit but not delete ───────────────────────────────

def test_operator_can_list_cars(operator_client):
    r = operator_client.get("/api/cars")
    assert r.status_code == 200


def test_operator_can_create_car(operator_client):
    r = operator_client.post("/api/cars", json={"car_type": "boxcar", "car_number": "1001", "reporting_marks": "UP"})
    assert r.status_code == 201


def test_operator_can_update_car(operator_client, db_session):
    car = make_car(db_session, "boxcar")
    r = operator_client.put(f"/api/cars/{car.id}", json={"car_type": "flatcar"})
    assert r.status_code == 200


def test_operator_cannot_delete_car(operator_client, db_session):
    car = make_car(db_session, "boxcar")
    r = operator_client.delete(f"/api/cars/{car.id}")
    assert r.status_code == 403


def test_admin_can_delete_car(admin_client, db_session):
    car = make_car(db_session, "boxcar")
    r = admin_client.delete(f"/api/cars/{car.id}")
    assert r.status_code == 204


# ── Dispatcher: operators cannot build/delete plans ──────────────────────────

def test_operator_cannot_build_dispatch_plan(operator_client, db_session):
    from models import SwitchingArea
    area = SwitchingArea(name="Yard", car_capacity=10)
    db_session.add(area)
    db_session.flush()
    origin = make_location(db_session, "Staging", "staging")
    dest = make_location(db_session, "Yard", "yard")
    r = operator_client.post("/api/dispatcher/build-plan", json={
        "switching_area_id": area.id,
        "origin_location_id": origin.id,
        "destination_location_id": dest.id,
    })
    assert r.status_code == 403


def test_operator_cannot_delete_dispatch_plan(operator_client, db_session):
    from models import DispatchPlan
    import json
    plan = DispatchPlan(
        plan_type="switching", status="draft",
        setout_ids_json="[]", pickup_ids_json="[]",
        spots_ids_json="[]", available_spots=0, built_at=0,
    )
    db_session.add(plan)
    db_session.flush()
    r = operator_client.delete(f"/api/dispatcher/plan/{plan.id}")
    assert r.status_code == 403


def test_operator_can_update_plan_status(operator_client, db_session):
    from models import DispatchPlan
    plan = DispatchPlan(
        plan_type="switching", status="draft",
        setout_ids_json="[]", pickup_ids_json="[]",
        spots_ids_json="[]", available_spots=0, built_at=0,
    )
    db_session.add(plan)
    db_session.flush()
    r = operator_client.patch(f"/api/dispatcher/plan/{plan.id}/status", json={"status": "active"})
    assert r.status_code == 200


def test_operator_cannot_update_plan_identity(operator_client, db_session):
    from models import DispatchPlan
    plan = DispatchPlan(
        plan_type="switching", status="draft",
        setout_ids_json="[]", pickup_ids_json="[]",
        spots_ids_json="[]", available_spots=0, built_at=0,
    )
    db_session.add(plan)
    db_session.flush()
    r = operator_client.patch(f"/api/dispatcher/plan/{plan.id}/identity",
                               json={"train_number": "MBW-101"})
    assert r.status_code == 403
