# SPDX-FileCopyrightText: 2026 David Dalzell
# SPDX-License-Identifier: MIT

"""Perf-guard regression tests for docs/perf-800-cars.md Phase 1.

GET /api/cars and GET /api/operations must issue a query count independent
of the number of cars (eager loading via selectinload, not one lazy-load
per car). Each test seeds a small batch, measures, seeds a much larger
batch on top, measures again, and asserts the query count barely moved —
catching a future N+1 regression even though both counts are "small" in
absolute terms at this test's scale.
"""

from sqlalchemy import event

from tests.conftest import make_car, make_industry, make_location, make_waybill


class QueryCounter:
    """Counts statements executed against one engine while active."""

    def __init__(self, engine):
        self.engine = engine
        self.count = 0

    def _on_execute(self, *args, **kwargs):
        self.count += 1

    def __enter__(self):
        event.listen(self.engine, "before_cursor_execute", self._on_execute)
        return self

    def __exit__(self, *exc):
        event.remove(self.engine, "before_cursor_execute", self._on_execute)


def _seed_cars_with_waybills(db_session, n, start=0):
    origin = make_location(db_session, "Staging", loc_type="staging")
    dest_group = make_location(db_session, "Mill Spur", loc_type="industry")
    industry = make_industry(db_session, "Grain Mill", location_id=dest_group.id)
    for i in range(n):
        car = make_car(db_session, location_id=origin.id)
        make_waybill(
            db_session, origin_id=origin.id, destination_id=dest_group.id,
            industry_id=industry.id, car_id=car.id, slot_index=0,
            name=f"car-{start + i}",
        )
    db_session.commit()


def test_get_cars_query_count_independent_of_roster_size(client, db_session):
    engine = db_session.get_bind()

    _seed_cars_with_waybills(db_session, 2)
    with QueryCounter(engine) as small:
        resp = client.get("/api/cars")
    assert resp.status_code == 200
    assert len(resp.json()) == 2

    _seed_cars_with_waybills(db_session, 18, start=2)
    with QueryCounter(engine) as large:
        resp = client.get("/api/cars")
    assert resp.status_code == 200
    assert len(resp.json()) == 20

    # 10x the cars should not meaningfully increase the query count — an N+1
    # regression here would scale `large.count` roughly linearly with roster
    # size instead of staying flat.
    assert large.count <= small.count + 2, (
        f"GET /api/cars query count scaled with roster size: "
        f"{small.count} queries for 2 cars, {large.count} for 20 — looks like an N+1 regression"
    )


def test_get_operations_query_count_independent_of_roster_size(client, db_session):
    engine = db_session.get_bind()

    _seed_cars_with_waybills(db_session, 2)
    with QueryCounter(engine) as small:
        resp = client.get("/api/operations")
    assert resp.status_code == 200
    assert len(resp.json()) == 2

    _seed_cars_with_waybills(db_session, 18, start=2)
    with QueryCounter(engine) as large:
        resp = client.get("/api/operations")
    assert resp.status_code == 200
    assert len(resp.json()) == 20

    assert large.count <= small.count + 2, (
        f"GET /api/operations query count scaled with roster size: "
        f"{small.count} queries for 2 cars, {large.count} for 20 — looks like an N+1 regression"
    )
