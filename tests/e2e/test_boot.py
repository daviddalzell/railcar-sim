"""App-boot smoke test — the single highest-value guard against the regression
class this frontend refactor could introduce: a `<script>` load-order break or a
missing/renamed static module. If the app loads clean with every JS/CSS module
served and no console errors, the module split is wired correctly."""

from playwright.sync_api import Page, expect

EXPECTED_JS_MODULES = [
    "state.js",
    "helpers.js",
    "clock.js",
    "export-import.js",
    "settings.js",
    "layout.js",
    "operations.js",
    "app.js",
]


def test_app_boots_clean(page: Page):
    console_errors = []
    page.on("console", lambda msg: console_errors.append(msg.text) if msg.type == "error" else None)
    page.on("pageerror", lambda exc: console_errors.append(str(exc)))

    static_responses = {}
    page.on(
        "response",
        lambda r: static_responses.__setitem__(r.url, r.status)
        if ("/static/js/" in r.url or "/static/css/" in r.url or "/static/app.js" in r.url)
        else None,
    )

    page.goto("/")

    # The Roster tab is the default landing tab; wait for its nav link to render.
    expect(page.locator('.tab-link[data-tab="roster"]')).to_be_visible()
    expect(page.locator("#tab-roster")).to_be_visible()
    page.wait_for_load_state("networkidle")

    # Every static JS/CSS asset that was requested returned a success status.
    bad = {url: status for url, status in static_responses.items() if status >= 400}
    assert not bad, f"static assets failed to load: {bad}"

    # Every expected JS module actually loaded (catches a dropped/renamed <script>).
    loaded = "\n".join(static_responses)
    missing = [m for m in EXPECTED_JS_MODULES if m not in loaded]
    assert not missing, f"expected JS modules never requested: {missing}"

    assert not console_errors, f"console errors on boot: {console_errors}"
