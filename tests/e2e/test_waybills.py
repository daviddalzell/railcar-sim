"""Waybill flow — seed a minimal shipper/receiver layout via the REST API, then
drive the UI to generate waybills and confirm they land in the pool. Exercises
the generate dialog (`app.js`: `#btn-generate-waybills` → `#btn-confirm-generate`
→ `renderWaybillPool`) against the `/api/generate-waybills` automation endpoint.

State setup goes through the API (fast, robust); the UI drives only the behavior
under test — the established "seed via API, assert via UI" e2e pattern."""

from playwright.sync_api import Page, expect


def _seed_layout(page: Page):
    """Create a Location, a staging origin track, an industry track, and a
    consumer industry that receives grain in boxcars — the minimum setup that
    makes `/api/generate-waybills` produce at least one waybill."""
    loc = page.request.post("/api/locations", data={"name": "Seed Yard"}).json()["id"]
    page.request.post(
        "/api/tracks",
        data={"name": "Staging 1", "location_type": "staging", "location_id": loc},
    )
    mill_track = page.request.post(
        "/api/tracks",
        data={"name": "Mill Spur", "location_type": "industry", "location_id": loc},
    ).json()["id"]
    page.request.post(
        "/api/industries",
        data={
            "name": "Grain Mill",
            "location_id": mill_track,
            "commodities": "grain",
            "inbound_car_types": "boxcar",
            "industry_role": "consumer",
        },
    )


def test_generate_waybills(page: Page):
    page.goto("/")
    _seed_layout(page)

    page.locator('.tab-link[data-tab="waybills"]').click()
    expect(page.locator("#tab-waybills")).to_be_visible()

    page.locator("#btn-generate-waybills").click()
    expect(page.locator("#generate-waybills-dialog")).to_be_visible()
    # Default (append) mode generates on a single click; no replace confirm needed.
    page.locator("#btn-confirm-generate").click()

    expect(page.locator("#generate-waybills-dialog")).to_be_hidden()
    # The generated inbound waybill for the seeded industry appears in the pool.
    expect(page.locator("#waybill-pool-list")).to_contain_text("Grain Mill")
