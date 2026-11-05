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
