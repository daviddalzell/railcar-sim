# SPDX-FileCopyrightText: 2026 David Dalzell
# SPDX-License-Identifier: MIT

"""Converter response-shape tests (PR 2).

Locks in the compat-key removals from the Location/Track rename so a
regression can't silently break a frontend running against stale cache.
"""

import json

from converters import dispatch_plan_to_dict, location_group_to_dict, track_to_dict
from models import DispatchPlan, Location, Track


def test_track_to_dict_has_location_id_not_switching_area_id(db_session):
    group = Location(name="Yard Complex", car_capacity=20)
    db_session.add(group)
    db_session.flush()
    track = Track(name="Siding 1", location_type="yard", location_id=group.id, car_capacity=5)
    db_session.add(track)
    db_session.flush()

    d = track_to_dict(track)
    assert d["location_id"] == group.id
    assert "switching_area_id" not in d
    assert set(d.keys()) == {"id", "name", "location_type", "location_id", "car_capacity"}


def test_location_group_to_dict_uses_tracks_key(db_session):
    group = Location(name="Yard Complex", car_capacity=20)
    db_session.add(group)
    db_session.flush()
    db_session.add(Track(name="Siding 1", location_type="yard", location_id=group.id))
    db_session.flush()

    d = location_group_to_dict(group, db_session)
    assert "tracks" in d
    assert "locations" not in d
    assert d["tracks"][0]["name"] == "Siding 1"


def test_dispatch_plan_to_dict_has_location_name_not_switching_area(db_session):
    group = Location(name="Switch District", car_capacity=20)
    db_session.add(group)
    db_session.flush()
    origin = Track(name="Staging", location_type="staging")
    dest = Track(name="Yard", location_type="yard")
    db_session.add_all([origin, dest])
    db_session.flush()

    plan = DispatchPlan(
        plan_type="switching", status="draft",
        origin_location_id=origin.id,
        location_id=group.id,
        destination_location_id=dest.id,
        setout_ids_json="[]", pickup_ids_json="[]",
        spots_ids_json="[]", available_spots=0, built_at=0,
    )
    db_session.add(plan)
    db_session.flush()

    d = dispatch_plan_to_dict(plan, db_session)
    assert d["location_id"] == group.id
    assert d["location_name"] == "Switch District"
    assert "switching_area_id" not in d
    assert "switching_area_name" not in d
