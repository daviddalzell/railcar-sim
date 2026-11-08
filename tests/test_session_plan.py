# SPDX-FileCopyrightText: 2026 David Dalzell
# SPDX-License-Identifier: MIT

"""Quick Op Session plan-building (`/api/session/plan`, _build_session_plan)."""

from tests.conftest import make_car, make_location, make_waybill


def test_session_plan_excludes_locomotives_and_cabooses(client, db_session):
    """A locomotive or caboose that ends up with an active waybill must never be
    selected as a cargo move in the Quick Op switch list (issue #55)."""
    staging = make_location(db_session, "Staging", "staging")
    industry_track = make_location(db_session, "Mill Spur", "industry")
    db_session.commit()

    loco = make_car(db_session, "locomotive", staging.id)
    make_waybill(db_session, staging.id, industry_track.id, car_id=loco.id, slot_index=0)
    caboose = make_car(db_session, "caboose", staging.id)
    make_waybill(db_session, staging.id, industry_track.id, car_id=caboose.id, slot_index=0)
    boxcar = make_car(db_session, "boxcar", staging.id)
    make_waybill(db_session, staging.id, industry_track.id, car_id=boxcar.id, slot_index=0)
    db_session.commit()

    r = client.post("/api/session/plan")
    assert r.status_code == 200
    data = r.json()
    all_ids = [c["id"] for group in ("arrivals", "departures", "spots") for c in data[group]]
    assert loco.id not in all_ids
    assert caboose.id not in all_ids
    assert boxcar.id in all_ids
