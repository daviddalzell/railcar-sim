"""Layout flow — build a Location → Track → Industry through the UI and confirm
each level renders. Exercises the largest extracted module (`layout.js`:
`loadLayout`, `renderLocationTree`, `renderIndustryList`, the location/track/
industry forms) against the real `/api/locations`, `/api/tracks`,
`/api/industries` endpoints."""

from playwright.sync_api import Page, expect


def test_build_location_track_industry(page: Page):
    page.goto("/")
    page.locator('.tab-link[data-tab="layout"]').click()
    expect(page.locator("#tab-layout")).to_be_visible()

    # 1. Add a Location.
    page.locator("#btn-add-location-group").click()
    expect(page.locator("#lg-form")).to_be_visible()
    page.locator("#lg-name").fill("Test Yard")
    page.locator("#lg-form button[type=submit]").click()
    expect(page.locator("#location-tree")).to_contain_text("Test Yard")

    # 2. Add a Track under that Location (per-location "+ track" button in the tree).
    page.locator("#location-tree .add-track-to-group").first.click()
    expect(page.locator("#track-form")).to_be_visible()
    page.locator("#tf-name").fill("Yard Lead")
    page.locator("#track-form button[type=submit]").click()
    expect(page.locator("#location-tree")).to_contain_text("Yard Lead")

    # 3. Add an Industry on that Track.
    page.locator("#btn-add-industry").click()
    expect(page.locator("#industry-form")).to_be_visible()
    page.locator("#ind-name").fill("Riverside Grain")
    page.locator("#ind-location").select_option(label="Yard Lead")
    page.locator("#industry-form button[type=submit]").click()
    expect(page.locator("#industry-list")).to_contain_text("Riverside Grain")
