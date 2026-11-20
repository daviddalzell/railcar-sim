"""Dialog hygiene smoke — native <dialog> open/close. CLAUDE.md flags "dialog
won't dismiss" as a recurring bug class (a `display` rule left inline on a
<dialog> defeats `dialog:not([open]){display:none}`, so `.close()` leaves it
painted). This confirms a dialog opens and actually disappears when closed via
the delegated `rel="prev"` handler and via native Escape — i.e. no stuck paint."""

from playwright.sync_api import Page, expect


def test_dialog_opens_and_dismisses(page: Page):
    page.goto("/")
    page.locator('.tab-link[data-tab="waybills"]').click()

    dialog = page.locator("#generate-waybills-dialog")

    # Open, then close via the delegated rel="prev" × handler.
    page.locator("#btn-generate-waybills").click()
    expect(dialog).to_be_visible()
    page.locator("#close-generate-dialog").click()
    expect(dialog).to_be_hidden()

    # Re-open, then dismiss via native Escape — confirms no display:none paint-stick.
    page.locator("#btn-generate-waybills").click()
    expect(dialog).to_be_visible()
    page.keyboard.press("Escape")
    expect(dialog).to_be_hidden()


def test_mobile_car_detail_footer_buttons_equal_width(page: Page):
    """#89 — on mobile, the car-detail dialog's footer buttons stack full
    width, but one (#btn-auto-assign-car) kept a desktop-only `max-width`
    because the mobile override's selector list forgot to re-include it.
    An ID selector always beats a class selector regardless of media query,
    so a desktop ID rule not mirrored in the mobile override silently wins —
    same failure shape as the #60 Cancel-button margin bug. Pin the
    invariant (every footer button is the same width on mobile) so a future
    button added to this footer can't reintroduce it unnoticed."""
    page.set_viewport_size({"width": 390, "height": 844})
    page.request.post("/api/cars", data={"car_type": "boxcar", "reporting_marks": "T", "car_number": "1"})

    page.goto("/")
    page.locator(".car-card").first.click()
    expect(page.locator("#car-detail-dialog")).to_be_visible()

    widths = {
        b.bounding_box()["width"]
        for b in page.locator("#car-detail-dialog footer button").all()
    }
    assert len(widths) == 1, f"footer buttons have inconsistent widths on mobile: {widths}"
