# SPDX-FileCopyrightText: 2026 David Dalzell
# SPDX-License-Identifier: MIT

from models import Car, Location, Waybill
from tests.conftest import make_car, make_location, make_waybill


# ── Location deletion ──────────────────────────────────────────────────────────

def test_delete_staging_without_merge_returns_400(client, db_session):
    staging = make_location(db_session, "Staging A", "staging")
    db_session.commit()

    r = client.delete(f"/api/locations/{staging.id}")
    assert r.status_code == 400


def test_delete_staging_merge_redirects_cars(client, db_session):
    staging_a = make_location(db_session, "Staging A", "staging")
    staging_b = make_location(db_session, "Staging B", "staging")
    car = make_car(db_session, location_id=staging_a.id)
    db_session.commit()

    r = client.delete(f"/api/locations/{staging_a.id}?merge_into_id={staging_b.id}")
    assert r.status_code == 200
    db_session.refresh(car)
    assert car.current_location_id == staging_b.id


def test_delete_staging_merge_redirects_waybill_origin(client, db_session):
    staging_a = make_location(db_session, "Staging A", "staging")
    staging_b = make_location(db_session, "Staging B", "staging")
    yard = make_location(db_session, "Yard", "yard")
    wb = make_waybill(db_session, staging_a.id, yard.id)
    db_session.commit()

    r = client.delete(f"/api/locations/{staging_a.id}?merge_into_id={staging_b.id}")
    assert r.status_code == 200
    db_session.refresh(wb)
    assert wb.origin_id == staging_b.id


def test_delete_staging_source_location_gone(client, db_session):
    staging_a = make_location(db_session, "Staging A", "staging")
    staging_b = make_location(db_session, "Staging B", "staging")
    db_session.commit()

    r = client.delete(f"/api/locations/{staging_a.id}?merge_into_id={staging_b.id}")
    assert r.status_code == 200
    gone = db_session.get(Location, staging_a.id)
    assert gone is None


def test_delete_non_staging_with_cars_returns_409(client, db_session):
    yard = make_location(db_session, "Yard", "yard")
    make_car(db_session, location_id=yard.id)
    db_session.commit()

    r = client.delete(f"/api/locations/{yard.id}")
    assert r.status_code == 409
    assert "cars" in r.json()["detail"]


def test_delete_non_staging_no_cars_succeeds(client, db_session):
    yard = make_location(db_session, "Empty Yard", "yard")
    db_session.commit()

    r = client.delete(f"/api/locations/{yard.id}")
    assert r.status_code == 200
    assert r.json()["action"] == "deleted"
    gone = db_session.get(Location, yard.id)
    assert gone is None


def test_delete_non_staging_removes_referencing_waybills(client, db_session):
    staging = make_location(db_session, "Staging", "staging")
    yard = make_location(db_session, "Yard", "yard")
    make_waybill(db_session, staging.id, yard.id)
    db_session.commit()

    r = client.delete(f"/api/locations/{yard.id}")
    assert r.status_code == 200
    remaining = db_session.query(Waybill).all()
    assert len(remaining) == 0


# ── Car deletion ───────────────────────────────────────────────────────────────

def test_delete_car_unassigns_loaded_waybills(client, db_session):
    staging = make_location(db_session, "Staging", "staging")
    yard = make_location(db_session, "Yard", "yard")
    car = make_car(db_session, location_id=staging.id)
    wb = make_waybill(db_session, staging.id, yard.id,
                      is_empty=False, car_id=car.id, slot_index=0)
    db_session.commit()

    r = client.delete(f"/api/cars/{car.id}")
    assert r.status_code == 204
    # waybill still in DB but unassigned
    db_session.expire_all()
    still_there = db_session.get(Waybill, wb.id)
    assert still_there is not None
    assert still_there.car_id is None
    assert still_there.slot_index is None


# ── Industry deletion ──────────────────────────────────────────────────────────

def test_delete_industry_removes_unassigned_waybills(client, db_session):
    staging = make_location(db_session, "Staging", "staging")
    yard = make_location(db_session, "Yard", "yard")
    from models import Industry
    ind = Industry(name="Mine", location_id=yard.id, industry_role="consumer",
                   commodities="coal", inbound_car_types="hopper")
    db_session.add(ind)
    db_session.flush()
    make_waybill(db_session, staging.id, yard.id, industry_id=ind.id, car_id=None)
    db_session.commit()

    r = client.delete(f"/api/industries/{ind.id}")
    assert r.status_code == 204
    remaining = db_session.query(Waybill).all()
    assert len(remaining) == 0


def test_delete_industry_keeps_car_assigned_waybills(client, db_session):
    staging = make_location(db_session, "Staging", "staging")
    yard = make_location(db_session, "Yard", "yard")
    car = make_car(db_session, location_id=staging.id)
    from models import Industry
    ind = Industry(name="Mine", location_id=yard.id, industry_role="consumer",
                   commodities="coal", inbound_car_types="hopper")
    db_session.add(ind)
    db_session.flush()
    wb = make_waybill(db_session, staging.id, yard.id,
                      industry_id=ind.id, car_id=car.id, slot_index=0)
    db_session.commit()

    r = client.delete(f"/api/industries/{ind.id}")
    assert r.status_code == 204
    db_session.expire_all()
    still_there = db_session.get(Waybill, wb.id)
    assert still_there is not None
    assert still_there.car_id == car.id
