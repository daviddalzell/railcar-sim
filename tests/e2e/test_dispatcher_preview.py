"""Dispatcher build-preview edge cases from #64 — PR #50 added power-car-type
exclusion, the max-train-length cap, and removing a car from the preview
before confirming, all covered by backend TestClient tests
(tests/test_dispatcher.py) but never exercised through the real frontend JS
in static/js/operations.js. This file adds that missing browser-level
coverage.

Waybills are built directly (POST /api/waybills + PUT /cars/{id}/slots)
rather than through /api/generate-waybills + /api/auto-assign-waybills: the
live_server fixture shares one DB/session across every e2e test in this
file, and those two endpoints operate over the *entire* accumulated layout,
not just what the current test just seeded — auto-assign's random.shuffle
can hand a car a waybill generated for an earlier test's industry on a
different track, entirely by chance. These tests assert exact car
counts/locations, so they need deterministic seeding, not the shared pool."""

from playwright.sync_api import Page, expect


def _seed_dispatchable_layout(page: Page, num_cars=1):
    """Seed a staging Location (separate from the switching area, as on a
    real layout) + an Op Yard Location with an industry track, `num_cars`
    freight cars at staging each with a direct inbound waybill to that
    industry track, and a locomotive (no waybill) for power. Returns
    (staging_id, group_id, loco_id, mill_id).

    Staging deliberately lives in its OWN Location: putting it in the same
    Location as the industry would make the origin track count as "inside
    the area" too, so every car would match both the inbound and
    local-spots eligibility filters at once and get double-counted."""
    req = page.request
    staging_group = req.post("/api/locations", data={"name": "Staging"}).json()["id"]
    staging = req.post(
        "/api/tracks",
        data={"name": "Staging A", "location_type": "staging", "location_id": staging_group},
    ).json()["id"]
    group = req.post("/api/locations", data={"name": "Op Yard"}).json()["id"]
    mill = req.post(
        "/api/tracks",
        data={"name": "Mill Spur", "location_type": "industry", "location_id": group},
    ).json()["id"]

    for i in range(num_cars):
        car_id = req.post(
            "/api/cars",
            data={"car_type": "boxcar", "reporting_marks": "BNSF",
                  "car_number": str(i + 1), "current_location_id": staging},
        ).json()["id"]
        wb_id = req.post(
            "/api/waybills",
            data={"name": "test-wb", "origin_id": staging, "destination_id": mill,
                  "commodity": "grain", "required_car_type": "boxcar"},
        ).json()["id"]
        req.put(f"/api/cars/{car_id}/slots", data={"slots": [{"slot_index": 0, "waybill_id": wb_id}]})

    loco = req.post(
        "/api/cars",
        data={"car_type": "locomotive", "reporting_marks": "ENG",
              "car_number": "99", "current_location_id": staging},
    ).json()["id"]
    return staging, group, loco, mill


def _open_dispatcher_and_build(page: Page, staging: int, group: int):
    page.goto("/")
    page.locator('.tab-link[data-tab="operations"]').click()
    expect(page.locator("#tab-operations")).to_be_visible()
    page.locator("#disp-origin").select_option(str(staging))
    page.locator("#disp-area").select_option(str(group))
    page.locator("#disp-destination").select_option(str(staging))
    page.locator("#btn-build-consist").click()
    expect(page.locator("#disp-preview .disp-preview-confirm")).to_be_visible()


def test_remove_car_from_preview_excludes_it_from_consist(page: Page):
    """Clicking the remove (✕) button on a car in the build preview actually
    excludes it from the committed consist, not just from the preview."""
    staging, group, _loco, _mill = _seed_dispatchable_layout(page, num_cars=2)
    _open_dispatcher_and_build(page, staging, group)

    preview = page.locator("#disp-preview")
    expect(preview.locator(".session-car-row")).to_have_count(2)
    removed_id = int(preview.locator(".car-row-remove").first.get_attribute("data-car-id"))

    preview.locator(".car-row-remove").first.click()
    expect(preview.locator(".session-car-row")).to_have_count(1)

    with page.expect_response(lambda r: "/api/dispatcher/build-plan" in r.url) as resp_info:
        preview.locator(".disp-preview-confirm").click()
    plan = resp_info.value.json()

    all_car_ids = {c["id"] for c in plan["setouts"] + plan["pickups"] + plan["spots"]}
    assert removed_id not in all_car_ids, "removed car made it into the committed consist"
    assert len(all_car_ids) == 1, f"expected exactly 1 car in the consist, got {all_car_ids}"


def test_max_train_length_caps_inbound_cars(page: Page):
    """Setting a max train length in settings is reflected in a subsequent
    dispatcher preview: only that many cars are included, with a warning."""
    staging, group, _loco, _mill = _seed_dispatchable_layout(page, num_cars=2)
    page.request.put(
        "/api/settings",
        data={"clock_start_time": "08:00", "clock_speed": 4, "ops_mode": "free",
              "max_train_length": 1},
    )

    _open_dispatcher_and_build(page, staging, group)

    preview = page.locator("#disp-preview")
    expect(preview.locator(".session-car-row")).to_have_count(1)
    expect(preview).to_contain_text("length limit")


def test_locomotive_with_waybill_excluded_from_consist(page: Page):
    """A locomotive is never pulled as a regular car even when it has an
    active waybill pointing at a valid in-area destination."""
    staging, group, loco, mill = _seed_dispatchable_layout(page, num_cars=1)

    # Give the locomotive the same shape of inbound waybill a normal car
    # would get (staging -> mill) — nothing does this on its own since no
    # commodity maps to "locomotive" — to confirm it's excluded by car type,
    # not merely because it never had a matching waybill in the first place.
    wb_id = page.request.post(
        "/api/waybills",
        data={"name": "loco-test-wb", "origin_id": staging, "destination_id": mill},
    ).json()["id"]
    page.request.put(
        f"/api/cars/{loco}/slots",
        data={"slots": [{"slot_index": 0, "waybill_id": wb_id}]},
    )

    _open_dispatcher_and_build(page, staging, group)

    expect(page.locator("#disp-preview")).not_to_contain_text("ENG 99")
