# SPDX-FileCopyrightText: 2026 David Dalzell
# SPDX-License-Identifier: MIT

"""Manual ordering of tracks (within a Location) and industries (within a Track)."""

from tests.conftest import make_industry, make_location


def _track_order(client, location_id):
    rows = client.get("/api/tracks").json()
    return [r["name"] for r in rows if r["location_id"] == location_id]


def _industry_order(client, track_id):
    rows = client.get("/api/industries").json()
    return [r["name"] for r in rows if r["location_id"] == track_id]


def _location_order(client):
    return [r["name"] for r in client.get("/api/locations").json()]


def test_move_location_reorders(client):
    ids = {}
    for name in ("L1", "L2", "L3"):
        ids[name] = client.post("/api/locations", json={"name": name, "car_capacity": 10}).json()["id"]

    assert _location_order(client) == ["L1", "L2", "L3"]

    r = client.post(f"/api/locations/{ids['L3']}/move", json={"direction": "up"})
    assert r.status_code == 200
    assert _location_order(client) == ["L1", "L3", "L2"]

    client.post(f"/api/locations/{ids['L1']}/move", json={"direction": "down"})
    assert _location_order(client) == ["L3", "L1", "L2"]


def test_create_track_sets_position(client):
    loc = client.post("/api/locations", json={"name": "Yard", "car_capacity": 10}).json()
    t = client.post("/api/tracks", json={
        "name": "T1", "location_type": "yard", "location_id": loc["id"]}).json()
    assert t["position"] is not None


def test_move_track_reorders_within_location(client):
    loc = client.post("/api/locations", json={"name": "Yard", "car_capacity": 10}).json()
    ids = {}
    for name in ("T1", "T2", "T3"):
        ids[name] = client.post("/api/tracks", json={
            "name": name, "location_type": "yard", "location_id": loc["id"]}).json()["id"]

    assert _track_order(client, loc["id"]) == ["T1", "T2", "T3"]

    r = client.post(f"/api/tracks/{ids['T3']}/move", json={"direction": "up"})
    assert r.status_code == 200
    assert _track_order(client, loc["id"]) == ["T1", "T3", "T2"]

    client.post(f"/api/tracks/{ids['T1']}/move", json={"direction": "down"})
    assert _track_order(client, loc["id"]) == ["T3", "T1", "T2"]


def test_move_track_at_edge_is_noop(client):
    loc = client.post("/api/locations", json={"name": "Yard", "car_capacity": 10}).json()
    t1 = client.post("/api/tracks", json={
        "name": "T1", "location_type": "yard", "location_id": loc["id"]}).json()
    client.post("/api/tracks", json={
        "name": "T2", "location_type": "yard", "location_id": loc["id"]})

    r = client.post(f"/api/tracks/{t1['id']}/move", json={"direction": "up"})  # already first
    assert r.status_code == 200
    assert _track_order(client, loc["id"]) == ["T1", "T2"]


def test_move_track_unknown_404(client):
    r = client.post("/api/tracks/99999/move", json={"direction": "up"})
    assert r.status_code == 404


def test_move_industry_reorders_within_track(client, db_session):
    """Factory industries have a NULL position; the move must normalise and reorder."""
    track = make_location(db_session, "Siding", "industry")
    i1 = make_industry(db_session, "I1", track.id)
    i2 = make_industry(db_session, "I2", track.id)
    i3 = make_industry(db_session, "I3", track.id)
    db_session.commit()

    assert _industry_order(client, track.id) == ["I1", "I2", "I3"]

    r = client.post(f"/api/industries/{i3.id}/move", json={"direction": "up"})
    assert r.status_code == 200
    assert _industry_order(client, track.id) == ["I1", "I3", "I2"]

    client.post(f"/api/industries/{i1.id}/move", json={"direction": "down"})
    assert _industry_order(client, track.id) == ["I3", "I1", "I2"]
