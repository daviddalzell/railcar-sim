# SPDX-FileCopyrightText: 2026 David Dalzell
# SPDX-License-Identifier: MIT

"""Industry intensity (weighted waybill selection) and car demurrage
(dwell turns) — issue #74."""

from models import Location, SessionClock
from routers.automation import industry_weight, weighted_shuffle
from routers.dispatcher import _run_build_algorithm
from routers.session import _build_session_plan
from tests.conftest import make_car, make_commodity_map, make_industry, make_location, make_waybill


# ── Intensity: industry_weight / weighted_shuffle ───────────────────────────

def test_industry_weight_defaults_to_one_when_unconfigured(db_session):
    loc = make_location(db_session, "Yard", "yard")
    ind = make_industry(db_session, "Quiet Mill", loc.id)
    db_session.commit()
    wb = make_waybill(db_session, loc.id, loc.id, industry_id=ind.id)
    db_session.commit()
    assert industry_weight(wb) == 1


def test_industry_weight_uses_avg_monthly_carloads(db_session):
    loc = make_location(db_session, "Yard", "yard")
    ind = make_industry(db_session, "Busy Mill", loc.id)
    ind.avg_monthly_carloads = 25
    db_session.commit()
    wb = make_waybill(db_session, loc.id, loc.id, industry_id=ind.id)
    db_session.commit()
    assert industry_weight(wb) == 25


def test_industry_weight_floors_at_one_for_zero(db_session):
    loc = make_location(db_session, "Yard", "yard")
    ind = make_industry(db_session, "Weird Mill", loc.id)
    ind.avg_monthly_carloads = 0
    db_session.commit()
    wb = make_waybill(db_session, loc.id, loc.id, industry_id=ind.id)
    db_session.commit()
    assert industry_weight(wb) == 1


def test_weighted_shuffle_favors_higher_weight_industry(db_session):
    loc = make_location(db_session, "Yard", "yard")
    quiet = make_industry(db_session, "Quiet Mill", loc.id)
    busy = make_industry(db_session, "Busy Mill", loc.id)
    busy.avg_monthly_carloads = 50
    db_session.commit()
    wb_quiet = make_waybill(db_session, loc.id, loc.id, industry_id=quiet.id, name="quiet")
    wb_busy = make_waybill(db_session, loc.id, loc.id, industry_id=busy.id, name="busy")
    db_session.commit()

    trials = 300
    busy_first_count = 0
    for _ in range(trials):
        pair = [wb_quiet, wb_busy]
        weighted_shuffle(pair)
        if pair[0] is wb_busy:
            busy_first_count += 1
    # Weight 50 vs weight 1 — busy should win the draw the vast majority of the time.
    assert busy_first_count > trials * 0.85


def test_weighted_shuffle_is_not_fixed_order_when_weights_equal(db_session):
    loc = make_location(db_session, "Yard", "yard")
    ind = make_industry(db_session, "Mill", loc.id)
    db_session.commit()
    wbs = [make_waybill(db_session, loc.id, loc.id, industry_id=ind.id, name=f"wb{i}") for i in range(3)]
    db_session.commit()

    orders = set()
    for _ in range(200):
        pool = list(wbs)
        weighted_shuffle(pool)
        orders.add(tuple(w.id for w in pool))
    # All weights equal (unconfigured industry) must reduce to an ordinary
    # shuffle, not an accidentally-fixed order.
    assert len(orders) > 1


# ── Demurrage: roll at arrival, increment, idempotency ──────────────────────

def test_dwell_rolled_and_reset_on_arrival(client, db_session):
    db_session.add(SessionClock(id=1))
    staging = make_location(db_session, "Staging", "staging")
    industry_track = make_location(db_session, "Mill Spur", "industry")
    ind = make_industry(db_session, "Grain Mill", industry_track.id)
    ind.dwell_multiplier = 2.0
    cmap = make_commodity_map(db_session, "grain", "covered hopper")
    cmap.base_dwell_turns = 3
    car = make_car(db_session, "covered hopper", staging.id)
    wb = make_waybill(db_session, staging.id, industry_track.id, industry_id=ind.id, car_id=car.id, slot_index=0)
    wb.commodity = "GRAIN"  # mixed case — exercises the .strip().lower() lookup fix
    db_session.commit()

    r = client.post("/api/session/end", json={"cars": [{"car_id": car.id, "status": "done"}]})
    assert r.status_code == 200
    db_session.refresh(car)
    # base 3 * multiplier 2.0 = 6, jitter in [-1, 0, 0, 1] -> 5..7
    assert 5 <= car.dwell_turns_required <= 7
    assert car.dwell_turns_elapsed == 0


def test_dwell_increments_untouched_car_but_not_cp_car(client, db_session):
    db_session.add(SessionClock(id=1))
    staging = make_location(db_session, "Staging", "staging")
    industry_track = make_location(db_session, "Mill Spur", "industry")
    overflow = make_location(db_session, "Overflow", "storage")

    moved_car = make_car(db_session, "boxcar", staging.id)
    make_waybill(db_session, staging.id, industry_track.id, car_id=moved_car.id, slot_index=0)

    untouched_car = make_car(db_session, "boxcar", industry_track.id)
    untouched_car.dwell_turns_elapsed = 2
    untouched_car.dwell_turns_required = 5

    cp_car = make_car(db_session, "boxcar", staging.id)
    make_waybill(db_session, staging.id, industry_track.id, car_id=cp_car.id, slot_index=0)
    cp_car.dwell_turns_elapsed = 2
    cp_car.dwell_turns_required = 5
    db_session.commit()

    r = client.post("/api/session/end", json={
        "cars": [
            {"car_id": moved_car.id, "status": "done"},
            {"car_id": cp_car.id, "status": "cp", "location_id": overflow.id},
        ],
    })
    assert r.status_code == 200

    db_session.refresh(untouched_car)
    db_session.refresh(cp_car)
    assert untouched_car.dwell_turns_elapsed == 3  # +1 — never touched this session
    assert cp_car.dwell_turns_elapsed == 2  # CP car's dwell clock stays frozen
    assert cp_car.dwell_turns_required == 5


def test_session_end_idempotent_does_not_double_increment(client, db_session):
    db_session.add(SessionClock(id=1))
    loc = make_location(db_session, "Mill Spur", "industry")
    car = make_car(db_session, "boxcar", loc.id)
    car.dwell_turns_elapsed = 0
    car.dwell_turns_required = 3
    db_session.commit()

    r1 = client.post("/api/session/end", json={"cars": []})
    assert r1.status_code == 200
    db_session.refresh(car)
    assert car.dwell_turns_elapsed == 1

    r2 = client.post("/api/session/end", json={"cars": []})
    assert r2.status_code == 200
    assert r2.json() == {"updated": []}
    db_session.refresh(car)
    assert car.dwell_turns_elapsed == 1  # second call is a no-op — clock already cleared


# ── Gating: dwell excludes a car from automatic selection until satisfied ───

def test_dispatcher_outbound_excludes_still_dwelling_car(db_session):
    area = Location(name="Industrial Park", car_capacity=20)
    db_session.add(area)
    db_session.flush()
    origin = make_location(db_session, "Staging", "staging")
    dest_yard = make_location(db_session, "Yard", "yard")
    industry_track = make_location(db_session, "Mill Spur", "industry")
    industry_track.location_id = area.id
    db_session.flush()

    dwelling_car = make_car(db_session, "boxcar", industry_track.id)
    make_waybill(db_session, industry_track.id, dest_yard.id, car_id=dwelling_car.id, slot_index=0)
    dwelling_car.dwell_turns_elapsed = 0
    dwelling_car.dwell_turns_required = 3

    ready_car = make_car(db_session, "boxcar", industry_track.id)
    make_waybill(db_session, industry_track.id, dest_yard.id, car_id=ready_car.id, slot_index=0)
    ready_car.dwell_turns_elapsed = 3
    ready_car.dwell_turns_required = 3
    db_session.commit()

    _, outbound, _, _, warnings = _run_build_algorithm(origin.id, area.id, dest_yard.id, db_session)
    outbound_ids = {c.id for c in outbound}
    assert dwelling_car.id not in outbound_ids
    assert ready_car.id in outbound_ids
    assert any("dwelling" in w for w in warnings)


def test_build_session_plan_excludes_still_dwelling_car(db_session):
    staging = make_location(db_session, "Staging", "staging")
    industry_track = make_location(db_session, "Mill Spur", "industry")

    dwelling_car = make_car(db_session, "boxcar", industry_track.id)
    make_waybill(db_session, industry_track.id, staging.id, car_id=dwelling_car.id, slot_index=0)
    dwelling_car.dwell_turns_elapsed = 0
    dwelling_car.dwell_turns_required = 2

    ready_car = make_car(db_session, "boxcar", industry_track.id)
    make_waybill(db_session, industry_track.id, staging.id, car_id=ready_car.id, slot_index=0)
    ready_car.dwell_turns_elapsed = 2
    ready_car.dwell_turns_required = 2
    db_session.commit()

    plan = _build_session_plan(db_session)
    departure_ids = {c["id"] for c in plan["departures"]}
    assert dwelling_car.id not in departure_ids
    assert ready_car.id in departure_ids
    assert any("dwelling" in w for w in plan["warnings"])
