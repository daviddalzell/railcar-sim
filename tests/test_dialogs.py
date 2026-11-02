# SPDX-FileCopyrightText: 2026 David Dalzell
# SPDX-License-Identifier: MIT

"""Dialog markup lint — guards against the recurring "dialog won't dismiss" bugs.

Two historical root causes, each a template mistake this test rejects:

1. Inline `display:` on a <dialog>. It overrides the browser rule
   `dialog:not([open]) { display: none }`, so .close() leaves the dialog
   painted. (demo-welcome, ai-notice, ai-region)
2. `rel="prev"` on a button that has visible text. PicoCSS styles a
   `rel="prev"` button as the small close-icon, so the text wraps vertically
   and the control is unusable. `rel="prev"` is for the empty header × only.
   (feedback dialog Cancel button)

The delegated close handler in static/app.js handles the "no handler" case;
this lint handles the two markup cases above.
"""

import re
from pathlib import Path

INDEX = Path(__file__).resolve().parent.parent / "templates" / "index.html"

DIALOG_RE = re.compile(r"(<dialog\b[^>]*>)(.*?)</dialog>", re.DOTALL)
STYLE_RE = re.compile(r'style="([^"]*)"')
ID_RE = re.compile(r'id="([^"]+)"')
REL_PREV_TEXT_RE = re.compile(
    r'<button[^>]*\brel="prev"[^>]*>\s*([^<\s][^<]*?)\s*</button>'
)


def _dialogs():
    html = INDEX.read_text()
    for m in DIALOG_RE.finditer(html):
        open_tag, body = m.group(1), m.group(2)
        did = (ID_RE.search(open_tag) or [None, "(no id)"])[1]
        yield did, open_tag, body


def test_no_dialog_has_inline_display():
    """A <dialog> must not set `display` inline — it breaks .close()."""
    offenders = []
    for did, open_tag, _ in _dialogs():
        style = STYLE_RE.search(open_tag)
        if style and "display:" in style.group(1):
            offenders.append(did)
    assert not offenders, (
        "These dialogs set `display` inline, which overrides "
        "`dialog:not([open]) { display: none }` and prevents .close() from "
        f"hiding them: {offenders}. Move the display rule into an "
        "[open]-scoped CSS rule instead."
    )


def test_no_rel_prev_button_has_text():
    """`rel="prev"` is for the empty header × only. A text button with it gets
    styled as the close-icon by PicoCSS and renders squished."""
    offenders = []
    for did, _, body in _dialogs():
        for text in REL_PREV_TEXT_RE.findall(body):
            offenders.append(f"{did}: {text!r}")
    assert not offenders, (
        "These buttons use rel=\"prev\" but have visible text, so PicoCSS "
        f"squishes them into the close-icon: {offenders}. Drop rel=\"prev\" "
        "from text buttons; keep it only on the empty header × button."
    )
