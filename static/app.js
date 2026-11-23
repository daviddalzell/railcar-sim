// SPDX-FileCopyrightText: 2026 David Dalzell
// SPDX-License-Identifier: MIT

/* Rail Car Movement Simulator — frontend */

// ── Helpers ───────────────────────────────────────────────────────────────────
// $, $$, api, show, hide, showToast, emptyState, withLoading, track,
// photoSrc, _authToken, _subscriberId now live in static/js/helpers.js,
// loaded before this file as a shared classic-script global.

function showOnlyLayoutForm(formEl) {
  ["#lg-form", "#track-form", "#industry-form"].forEach(sel => { const f = $(sel); if (f) hide(f); });
  if (formEl) show(formEl);
}

// Guard: one delegated handler closes the nearest <dialog> for any close
// control — a `rel="prev"` button (the header × convention) or a `.dialog-close`
// element. Dialogs then dismiss even when a per-dialog handler is missing.
document.addEventListener("click", e => {
  const closer = e.target.closest('dialog [rel="prev"], dialog .dialog-close');
  if (closer) closer.closest("dialog")?.close();
});

// Close any open Layout Setup tree-row overflow (kebab) menu on outside
// click or Escape — the kebab's own click handler stops propagation, so
// this only ever sees clicks that should close it.
function closeAllTreeMenus() {
  document.querySelectorAll("#location-tree .tree-actions.menu-open").forEach(el => el.classList.remove("menu-open"));
}
document.addEventListener("click", closeAllTreeMenus);

// Close the Layout Setup Data actions menu (#65) the same way — its own
// trigger/panel click handlers in export-import.js stopPropagation/call
// this directly, so this only ever sees clicks that should close it.
function closeDataMenu() {
  const menu = $("#layout-data-menu");
  if (!menu) return;
  menu.classList.remove("open");
  $("#btn-layout-data-menu")?.setAttribute("aria-expanded", "false");
}
document.addEventListener("click", closeDataMenu);
document.addEventListener("keydown", e => { if (e.key === "Escape") { closeAllTreeMenus(); closeDataMenu(); } });

// ── Tab navigation ────────────────────────────────────────────────────────────
const navTabList   = $("#nav-tab-list");
const navHamburger = $("#nav-hamburger");
const navCurrentTab = $("#nav-current-tab");
if (navCurrentTab) navCurrentTab.textContent = "Car Roster";
if (navHamburger) {
  navHamburger.addEventListener("click", () => navTabList.classList.toggle("nav-open"));
}

$$(".tab-link").forEach(link => {
  link.addEventListener("click", e => {
    e.preventDefault();
    navTabList?.classList.remove("nav-open");
    const tab = link.dataset.tab;
    if (!tab) return;  // non-tab links (e.g. "Send feedback") handle their own click
    $$(".tab-link").forEach(l => l.classList.remove("active"));
    $$(".tab-panel").forEach(p => p.classList.add("hidden"));
    link.classList.add("active");
    $(`#tab-${tab}`)?.classList.remove("hidden");
    if (navCurrentTab) navCurrentTab.textContent = link.textContent.trim();
    if (tab === "operations") loadOperations();
    if (tab === "waybills") loadWaybillPool();
    if (tab === "layout") loadLayout();
    if (tab === "settings") { loadSettings(); _startMembersRefresh(); } else { _stopMembersRefresh(); }
  });
});

// ── Ops/session thumbnail click → car detail ─────────────────────────────────
$("#ops-list").addEventListener("click", e => {
  const thumb = e.target.closest(".clickable-thumb");
  if (thumb) openCarDetail(parseInt(thumb.dataset.id));
});

// ── Help tab ──────────────────────────────────────────────────────────────────
$$(".help-section-header").forEach(btn => {
  btn.addEventListener("click", () => {
    const body = btn.nextElementSibling;
    const collapsed = body.classList.toggle("hidden");
    btn.textContent = (collapsed ? "▶" : "▼") + btn.textContent.slice(1);
  });
});

$("#help-search").addEventListener("input", e => {
  const q = e.target.value.trim().toLowerCase();
  $$(".help-section").forEach(section => {
    if (!q) {
      section.classList.remove("hidden");
      section.querySelector(".help-section-body").classList.add("hidden");
      const hdr = section.querySelector(".help-section-header");
      hdr.textContent = "▶" + hdr.textContent.slice(1);
    } else {
      const match = section.textContent.toLowerCase().includes(q);
      section.classList.toggle("hidden", !match);
      if (match) {
        section.querySelector(".help-section-body").classList.remove("hidden");
        const hdr = section.querySelector(".help-section-header");
        hdr.textContent = "▼" + hdr.textContent.slice(1);
      }
    }
  });
});

let helpAllExpanded = false;
$("#btn-help-expand-all").addEventListener("click", () => {
  helpAllExpanded = !helpAllExpanded;
  $$(".help-section-body").forEach(b => b.classList.toggle("hidden", !helpAllExpanded));
  $$(".help-section-header").forEach(h => {
    h.textContent = (helpAllExpanded ? "▼" : "▶") + h.textContent.slice(1);
  });
  $("#btn-help-expand-all").textContent = helpAllExpanded ? "Collapse All" : "Expand All";
});

// ── Bootstrap ─────────────────────────────────────────────────────────────────
(async function init() {
  // Wait for Supabase getSession() to finish before making authenticated API calls.
  // Without this, init() can fire while a token refresh is still in flight (app.js loads
  // from cache faster than getSession() resolves), sending all requests without a Bearer
  // token and returning empty data. In local/demo mode _authReady is undefined — skip.
  if (window._authReady) await window._authReady;
  _openOpsEventSource();
  await Promise.all([
    loadRoster(),
    (async () => {
      [[appState.locations, appState.industries, appState.waybillPool, appState.carTypes, appState.switchingAreas], appState.settings] = await Promise.all([
        Promise.all([
          api("GET", "/api/tracks"),
          api("GET", "/api/industries"),
          api("GET", "/api/waybills"),
          api("GET", "/api/car-types"),
          api("GET", "/api/locations"),
        ]),
        api("GET", "/api/settings"),
      ]);
      appState.opsMode = appState.settings?.ops_mode || "free";
      populateCarTypeSelects();
      // loadRoster() runs concurrently above, not after this — on a fast load it can
      // render before appState.carTypes exists, so default car-type images silently
      // fail to resolve on the very first paint. Re-render now that carTypes is in.
      renderCarGrid();
    })(),
  ]);
  document.querySelector('a[href*="patreon.com"]')
    ?.addEventListener("click", () => track("patreon_link_clicked"));

  // Demo welcome modal — once per browser session
  const demoWelcomeDlg = document.getElementById("demo-welcome-dialog");
  if (demoWelcomeDlg && !sessionStorage.getItem("demo_welcomed")) {
    sessionStorage.setItem("demo_welcomed", "1");
    demoWelcomeDlg.showModal();
  }

  // AI privacy notice — check at first launch (skipped for demo: welcome modal covers disclosure)
  if (!demoWelcomeDlg) {
    const tsData = await api("GET", "/api/tenant-settings").catch(() => null);
    if (tsData?.source === "tenant") {
      const restricted = tsData.is_restricted_region && tsData.ai_on_free_tier;
      if (restricted) {
        document.getElementById("ai-region-dialog")?.showModal();
        document.querySelectorAll(".ai-suggest-btn, #btn-stylize, #btn-add-car").forEach(btn => {
          btn.disabled = true;
          btn.title = "AI features unavailable in your region — add your own API key in Settings";
        });
      } else if (!tsData.ai_notice_acknowledged) {
        document.getElementById("ai-notice-dialog")?.showModal();
      }
    }
  }
})();

// ── AI notice button handlers ──────────────────────────────────────────────────
document.getElementById("btn-ai-notice-accept")?.addEventListener("click", async () => {
  await api("POST", "/api/tenant-settings/acknowledge-ai-notice").catch(() => null);
  document.getElementById("ai-notice-dialog")?.close();
});

document.getElementById("btn-region-open-settings")?.addEventListener("click", () => {
  document.getElementById("ai-region-dialog")?.close();
  document.querySelector('.tab-link[data-tab="settings"]')?.click();
  setTimeout(() => {
    document.getElementById("settings-gemini-key")?.scrollIntoView({ behavior: "smooth", block: "center" });
  }, 100);
});

document.getElementById("btn-region-close")?.addEventListener("click", () => {
  document.getElementById("ai-region-dialog")?.close();
});

// ── Demo welcome modal button handlers ────────────────────────────────────────
async function _submitDemoLead() {
  const email = (document.getElementById("demo-lead-email")?.value || "").trim();
  const marketing = document.getElementById("demo-lead-marketing")?.checked || false;
  if (email) {
    await fetch("/api/demo-leads", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, marketing_opt_in: marketing }),
    }).catch(() => null);
  }
  document.getElementById("demo-welcome-dialog")?.close();
}

document.getElementById("btn-demo-welcome-continue")?.addEventListener("click", _submitDemoLead);
document.getElementById("btn-demo-welcome-skip")?.addEventListener("click", () => {
  document.getElementById("demo-welcome-dialog")?.close();
});

// Enable "Continue to Demo" only when a valid email is entered.
// Users without an email use "No thanks, just explore" to enter.
(() => {
  const demoEmail = document.getElementById("demo-lead-email");
  const demoContinue = document.getElementById("btn-demo-welcome-continue");
  if (!demoEmail || !demoContinue) return;
  const syncDemoContinue = () => {
    demoContinue.disabled = !(demoEmail.value.trim() && demoEmail.checkValidity());
  };
  demoEmail.addEventListener("input", syncDemoContinue);
  syncDemoContinue();
})();
