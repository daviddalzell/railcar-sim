from models import Waybill
from tests.conftest import make_car, make_location, make_waybill


def test_assigns_loaded_waybill_from_staging(client, db_session):
    staging = make_location(db_session, "Staging", "staging")
    yard = make_location(db_session, "Yard", "yard")
    car = make_car(db_session, "boxcar", location_id=staging.id)
    make_waybill(db_session, staging.id, yard.id, is_empty=False)
    db_session.commit()

    r = client.post("/api/auto-assign-waybills")
    assert r.status_code == 200
    assert r.json()["assigned"] >= 1
    # waybill should now be assigned to the car
    wb = db_session.query(Waybill).filter(Waybill.car_id == car.id).first()
    assert wb is not None


def test_assigns_two_slots_loaded_then_empty(client, db_session):
    staging = make_location(db_session, "Staging", "staging")
    yard = make_location(db_session, "Yard", "yard")
    car = make_car(db_session, "boxcar", location_id=staging.id)
    loaded_wb = make_waybill(db_session, staging.id, yard.id, is_empty=False)
    make_waybill(db_session, yard.id, staging.id, is_empty=True)
    db_session.commit()

    r = client.post("/api/auto-assign-waybills")
    assert r.status_code == 200
    # Algorithm fills remaining slots via cloning, so at least 2 assigned
    assert r.json()["assigned"] >= 2
    # The specific loaded waybill must be in slot 0
    db_session.refresh(loaded_wb)
    assert loaded_wb.car_id == car.id
    assert loaded_wb.slot_index == 0


def test_no_unassigned_waybills_returns_zero(client, db_session):
    staging = make_location(db_session, "Staging", "staging")
    make_car(db_session, "boxcar", location_id=staging.id)
    db_session.commit()

    r = client.post("/api/auto-assign-waybills")
    assert r.status_code == 200
    assert r.json()["assigned"] == 0


def test_hopper_at_staging_takes_loaded_waybill(client, db_session):
    staging = make_location(db_session, "Staging", "staging")
    yard = make_location(db_session, "Yard", "yard")
    car = make_car(db_session, "hopper", location_id=staging.id)
    loaded_wb = make_waybill(db_session, staging.id, yard.id, is_empty=False)
    db_session.commit()

    r = client.post("/api/auto-assign-waybills")
    assert r.status_code == 200
    assert r.json()["assigned"] >= 1
    db_session.refresh(loaded_wb)
    assert loaded_wb.car_id == car.id


def test_hopper_at_industry_takes_empty_not_loaded(client, db_session):
    # For the single-car endpoint, staging_ids = staging + yard.
    # An "industry" location is outside staging_ids, so always_empty hoppers
    # at an industry look ONLY for empty returns, not loaded waybills.
    staging = make_location(db_session, "Staging", "staging")
    ind_loc = make_location(db_session, "Industry", "industry")
    car = make_car(db_session, "hopper", location_id=staging.id)
    # Route in: staging → industry (hopper picks this up first)
    make_waybill(db_session, staging.id, ind_loc.id, is_empty=False)
    # Empty return: industry → staging (hopper should take this for slot 1)
    empty_wb = make_waybill(db_session, ind_loc.id, staging.id, is_empty=True)
    # Loaded from industry: should NOT be taken by hopper at industry
    loaded_from_ind = make_waybill(db_session, ind_loc.id, staging.id, is_empty=False)
    db_session.commit()

    r = client.post(f"/api/cars/{car.id}/auto-assign")
    assert r.status_code == 200
    # Loaded waybill from industry must remain unassigned (hopper skips it)
    db_session.expire_all()
    db_session.refresh(loaded_from_ind)
    assert loaded_from_ind.car_id is None
    # A clone of the empty return waybill must be in slot 1 (empty wbs are cloned, not moved)
    slot1 = db_session.query(Waybill).filter(
        Waybill.car_id == car.id, Waybill.slot_index == 1
    ).first()
    assert slot1 is not None
    assert slot1.is_empty is True
    assert slot1.origin_id == ind_loc.id


def test_all_slots_occupied_skips_car(client, db_session):
    staging = make_location(db_session, "Staging", "staging")
    yard = make_location(db_session, "Yard", "yard")
    car = make_car(db_session, "boxcar", location_id=staging.id)
    # pre-fill all 4 slots directly
    for slot in range(4):
        make_waybill(db_session, staging.id, yard.id,
                     car_id=car.id, slot_index=slot)
    # extra unassigned waybill that would be taken if any slot were open
    make_waybill(db_session, staging.id, yard.id)
    db_session.commit()

    r = client.post("/api/auto-assign-waybills")
    assert r.status_code == 200
    assert r.json()["assigned"] == 0


def test_non_consecutive_slots_skips_car(client, db_session):
    staging = make_location(db_session, "Staging", "staging")
    yard = make_location(db_session, "Yard", "yard")
    car = make_car(db_session, "boxcar", location_id=staging.id)
    # slots 0 and 2 occupied — gap at 1 means open_slots [1,3] != expected [3,4]
    make_waybill(db_session, staging.id, yard.id, car_id=car.id, slot_index=0)
    make_waybill(db_session, yard.id, staging.id, car_id=car.id, slot_index=2, is_empty=True)
    make_waybill(db_session, staging.id, yard.id)  # unassigned to tempt assignment
    db_session.commit()

    r = client.post("/api/auto-assign-waybills")
    assert r.status_code == 200
    assert r.json()["assigned"] == 0


def test_two_cars_both_assigned(client, db_session):
    staging = make_location(db_session, "Staging", "staging")
    yard = make_location(db_session, "Yard", "yard")
    car1 = make_car(db_session, "boxcar", location_id=staging.id)
    car2 = make_car(db_session, "flatcar", location_id=staging.id)
    make_waybill(db_session, staging.id, yard.id, required_car_type="boxcar")
    make_waybill(db_session, staging.id, yard.id, required_car_type="flatcar")
    db_session.commit()

    r = client.post("/api/auto-assign-waybills")
    assert r.status_code == 200
    assert r.json()["assigned"] == 2


def test_car_type_mismatch_not_assigned(client, db_session):
    staging = make_location(db_session, "Staging", "staging")
    yard = make_location(db_session, "Yard", "yard")
    make_car(db_session, "hopper", location_id=staging.id)
    make_waybill(db_session, staging.id, yard.id, required_car_type="boxcar")
    db_session.commit()

    r = client.post("/api/auto-assign-waybills")
    assert r.status_code == 200
    assert r.json()["assigned"] == 0


def test_required_car_type_none_matches_any(client, db_session):
    staging = make_location(db_session, "Staging", "staging")
    yard = make_location(db_session, "Yard", "yard")
    car = make_car(db_session, "gondola", location_id=staging.id)
    make_waybill(db_session, staging.id, yard.id, required_car_type=None)
    db_session.commit()

    r = client.post("/api/auto-assign-waybills")
    assert r.status_code == 200
    assert r.json()["assigned"] >= 1
    wb = db_session.query(Waybill).filter(Waybill.car_id == car.id).first()
    assert wb is not None
