"""Dispatcher → operating-session lifecycle — the highest-value, most-coupled
flow (`operations.js`: dispatcher build, session start/mark/end, which call
across each other and into the clock). This test seeds a dispatchable layout via
the API, then drives the full UI lifecycle: build a consist, start a session,
mark a car worked, and end the session.

Note: this flow is what surfaced the `appState.session` and `Track.location_type`
regressions during development — exactly the coupling the module split risked."""

from playwright.sync_api import Page, expect


def _seed_dispatchable_layout(page: Page):
    """Seed a Location with a staging origin and an industry destination, a
    consumer industry, generated+assigned waybills, a freight car staged with an
    active waybill, and a locomotive for power. Returns (staging_id, group_id,
    loco_id) needed to drive the dispatcher UI."""
    req = page.request
    group = req.post("/api/locations", data={"name": "Op Yard"}).json()["id"]
    staging = req.post(
        "/api/tracks",
        data={"name": "Staging A", "location_type": "staging", "location_id": group},
    ).json()["id"]
    mill = req.post(
        "/api/tracks",
        data={"name": "Mill Spur", "location_type": "industry", "location_id": group},
    ).json()["id"]
    req.post(
        "/api/industries",
        data={
            "name": "Grain Mill",
            "location_id": mill,
            "commodities": "grain",
            "inbound_car_types": "boxcar",
            "industry_role": "consumer",
        },
    )
    req.post("/api/generate-waybills", data={"replace": True})
    req.post(
        "/api/cars",
        data={"car_type": "boxcar", "reporting_marks": "BNSF",
              "car_number": "1", "current_location_id": staging},
    )
    req.post("/api/auto-assign-waybills", data={})
    loco = req.post(
        "/api/cars",
        data={"car_type": "locomotive", "reporting_marks": "ENG",
              "car_number": "99", "current_location_id": staging},
    ).json()["id"]
    return staging, group, loco


def test_dispatch_and_run_session(page: Page):
    staging, group, loco = _seed_dispatchable_layout(page)

    page.goto("/")
    page.locator('.tab-link[data-tab="operations"]').click()
    expect(page.locator("#tab-operations")).to_be_visible()

    # Build a consist through the dispatcher.
    page.locator("#disp-origin").select_option(str(staging))
    page.locator("#disp-area").select_option(str(group))
    page.locator("#disp-destination").select_option(str(staging))
    page.locator("#btn-build-consist").click()

    start_btn = page.locator(".consist-start-session").first
    expect(start_btn).to_be_visible()
    plan_id = start_btn.get_attribute("data-plan-id")

    # Assign power via the API (the power <select> lives in a collapsed card
    # section; power assignment is setup, not the behavior under test), then
    # re-render the panel so the now-enabled Start button reflects it.
    resp = page.request.patch(
        f"/api/dispatcher/plan/{plan_id}/power",
        data={"power_ids": [loco], "caboose_id": None},
    )
    assert resp.ok, f"power assignment failed: {resp.status}"
    page.reload()
    page.locator('.tab-link[data-tab="operations"]').click()

    # Start the session from the consist.
    start_btn = page.locator(f".consist-start-session[data-plan-id='{plan_id}']").first
    expect(start_btn).to_be_enabled()
    start_btn.click()

    # The active session lists the staged car with work controls.
    expect(page.locator("#ops-list")).to_contain_text("BNSF 1")
    expect(page.locator(".session-done-btn").first).to_be_visible()

    # Mark one move done, then end the session.
    page.locator(".session-done-btn").first.click()
    page.locator("#btn-end-session").click()

    # Session ends: the active-session End button is gone and the consist is complete.
    expect(page.locator("#btn-end-session")).to_have_count(0)
