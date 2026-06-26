from models import Waybill
from tests.conftest import (
    make_car, make_commodity_map, make_industry, make_location, make_waybill,
)


def test_consumer_creates_inbound_waybill(client, db_session):
    staging = make_location(db_session, "Staging", "staging")
    yard = make_location(db_session, "Yard", "yard")
    make_industry(db_session, "Mill", yard.id, role="consumer",
                  inbound_commodities="coal", inbound_car_types="hopper")
    db_session.commit()

    r = client.post("/api/generate-waybills",
                    json={"origin_location_id": staging.id, "replace": False})
    assert r.status_code == 200
    loaded = [w for w in r.json()["waybills"] if not w["is_empty"]]
    # One loaded inbound waybill per staging/yard origin location
    assert len(loaded) == 2
    origin_ids = {w["origin_id"] for w in loaded}
    assert staging.id in origin_ids
    assert yard.id in origin_ids
    assert all(w["destination_id"] == yard.id for w in loaded)


def test_consumer_creates_empty_return_with_car_type(client, db_session):
    staging = make_location(db_session, "Staging", "staging")
    yard = make_location(db_session, "Yard", "yard")
    make_industry(db_session, "Mill", yard.id, role="consumer",
                  inbound_commodities="coal", inbound_car_types="hopper")
    db_session.commit()

    r = client.post("/api/generate-waybills",
                    json={"origin_location_id": staging.id, "replace": False})
    assert r.status_code == 200
    empty = [w for w in r.json()["waybills"] if w["is_empty"]]
    # One empty return waybill per staging/yard origin location
    assert len(empty) == 2
    assert all(w["name"] == "← Mill (empty hopper)" for w in empty)
    assert all(w["required_car_type"] == "hopper" for w in empty)


def test_producer_creates_outbound_waybill(client, db_session):
    staging = make_location(db_session, "Staging", "staging")
    yard = make_location(db_session, "Yard", "yard")
    make_industry(db_session, "Sawmill", yard.id, role="producer",
                  outbound_commodities="lumber", outbound_car_types="flatcar")
    db_session.commit()

    r = client.post("/api/generate-waybills",
                    json={"origin_location_id": staging.id, "replace": False})
    assert r.status_code == 200
    loaded = [w for w in r.json()["waybills"] if not w["is_empty"]]
    # One outbound loaded waybill per staging/yard destination
    assert len(loaded) == 2
    assert all(w["name"] == "lumber ← Sawmill" for w in loaded)
    assert all(w["origin_id"] == yard.id for w in loaded)
    dest_ids = {w["destination_id"] for w in loaded}
    assert staging.id in dest_ids


def test_producer_creates_empty_delivery(client, db_session):
    staging = make_location(db_session, "Staging", "staging")
    yard = make_location(db_session, "Yard", "yard")
    make_industry(db_session, "Sawmill", yard.id, role="producer",
                  outbound_commodities="lumber", outbound_car_types="flatcar")
    db_session.commit()

    r = client.post("/api/generate-waybills",
                    json={"origin_location_id": staging.id, "replace": False})
    assert r.status_code == 200
    empty = [w for w in r.json()["waybills"] if w["is_empty"]]
    # One empty delivery waybill per staging/yard origin location
    assert len(empty) == 2
    assert all(w["name"] == "→ Sawmill (empty flatcar)" for w in empty)
    dest_ids = {w["destination_id"] for w in empty}
    assert yard.id in dest_ids


def test_transload_creates_inbound_and_outbound(client, db_session):
    staging = make_location(db_session, "Staging", "staging")
    yard = make_location(db_session, "Yard", "yard")
    make_industry(db_session, "Transfer", yard.id, role="transload",
                  inbound_commodities="coal", inbound_car_types="hopper",
                  outbound_commodities="lumber", outbound_car_types="flatcar")
    db_session.commit()

    r = client.post("/api/generate-waybills",
                    json={"origin_location_id": staging.id, "replace": False})
    assert r.status_code == 200
    loaded = [w for w in r.json()["waybills"] if not w["is_empty"]]
    names = {w["name"] for w in loaded}
    assert "coal → Transfer" in names
    assert "lumber ← Transfer" in names


def test_replace_clears_existing_waybills(client, db_session):
    staging = make_location(db_session, "Staging", "staging")
    yard = make_location(db_session, "Yard", "yard")
    make_industry(db_session, "Mill", yard.id, role="consumer",
                  inbound_commodities="coal", inbound_car_types="hopper")
    # pre-existing unrelated waybill
    make_waybill(db_session, staging.id, yard.id, name="old")
    db_session.commit()

    r = client.post("/api/generate-waybills",
                    json={"origin_location_id": staging.id, "replace": True})
    assert r.status_code == 200
    # only the newly generated waybills should be in the DB
    all_wbs = db_session.query(Waybill).all()
    names = {w.name for w in all_wbs}
    assert "old" not in names


def test_no_replace_skips_duplicates(client, db_session):
    staging = make_location(db_session, "Staging", "staging")
    yard = make_location(db_session, "Yard", "yard")
    make_industry(db_session, "Mill", yard.id, role="consumer",
                  inbound_commodities="coal", inbound_car_types="hopper")
    db_session.commit()

    payload = {"origin_location_id": staging.id, "replace": False}
    client.post("/api/generate-waybills", json=payload)
    r2 = client.post("/api/generate-waybills", json=payload)
    assert r2.status_code == 200
    assert r2.json()["created"] == 0
    assert r2.json()["skipped"] > 0


def test_industry_without_location_skipped(client, db_session):
    staging = make_location(db_session, "Staging", "staging")
    # industry with no location
    from models import Industry
    ind = Industry(name="Ghost", location_id=None, industry_role="consumer",
                   commodities="coal", inbound_car_types="hopper")
    db_session.add(ind)
    db_session.commit()

    r = client.post("/api/generate-waybills",
                    json={"origin_location_id": staging.id, "replace": False})
    assert r.status_code == 200
    assert r.json()["created"] == 0


def test_waybill_name_patterns(client, db_session):
    staging = make_location(db_session, "Staging", "staging")
    yard = make_location(db_session, "Yard", "yard")
    make_industry(db_session, "Mill", yard.id, role="consumer",
                  inbound_commodities="coal", inbound_car_types="hopper")
    db_session.commit()

    r = client.post("/api/generate-waybills",
                    json={"origin_location_id": staging.id, "replace": False})
    assert r.status_code == 200
    names = {w["name"] for w in r.json()["waybills"]}
    assert "coal → Mill" in names
    assert "← Mill (empty hopper)" in names


def test_commodity_map_used_for_required_car_type(client, db_session):
    staging = make_location(db_session, "Staging", "staging")
    yard = make_location(db_session, "Yard", "yard")
    make_industry(db_session, "Mine", yard.id, role="consumer",
                  inbound_commodities="gravel")  # no inbound_car_types set
    make_commodity_map(db_session, "gravel", "gondola")
    db_session.commit()

    r = client.post("/api/generate-waybills",
                    json={"origin_location_id": staging.id, "replace": False})
    assert r.status_code == 200
    loaded = [w for w in r.json()["waybills"] if not w["is_empty"]]
    # One loaded inbound waybill per staging/yard origin location
    assert len(loaded) == 2
    assert all(w["required_car_type"] == "gondola" for w in loaded)


def test_wildcard_car_type_creates_generic_empty(client, db_session):
    staging = make_location(db_session, "Staging", "staging")
    yard = make_location(db_session, "Yard", "yard")
    make_industry(db_session, "Mill", yard.id, role="consumer",
                  inbound_commodities="coal", inbound_car_types="all")
    db_session.commit()

    r = client.post("/api/generate-waybills",
                    json={"origin_location_id": staging.id, "replace": False})
    assert r.status_code == 200
    empty = [w for w in r.json()["waybills"] if w["is_empty"]]
    # One generic empty return per staging/yard origin location
    assert len(empty) == 2
    assert all(w["name"] == "← Mill (empty)" for w in empty)
    assert all(w["required_car_type"] is None for w in empty)
