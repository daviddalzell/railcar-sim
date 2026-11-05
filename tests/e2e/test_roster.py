"""Roster flow — add a car manually through the UI and confirm it renders in the
grid. Exercises the Roster module (`app.js`: add-car form, `#btn-save-car`,
`renderCarGrid`) end to end against the real API."""

from playwright.sync_api import Page, expect


def test_add_car_manually(page: Page):
    page.goto("/")
    expect(page.locator("#tab-roster")).to_be_visible()

    page.locator("#btn-add-manual").click()
    expect(page.locator("#add-car-form")).to_be_visible()
    expect(page.locator("#car-fields")).to_be_visible()

    page.locator("#field-marks").fill("TESTX")
    page.locator("#field-number").fill("9001")
    # #field-type is seeded with default car types on a fresh DB; pick the first.
    page.locator("#field-type").select_option(index=0)
    page.locator("#field-color").fill("brown")

    page.locator("#btn-save-car").click()

    # The add-car form closes and the new car appears in the roster grid.
    expect(page.locator("#add-car-form")).to_be_hidden()
    expect(page.locator("#car-grid")).to_contain_text("TESTX")
    expect(page.locator("#car-grid")).to_contain_text("9001")
