// SPDX-FileCopyrightText: 2026 David Dalzell
// SPDX-License-Identifier: MIT

/* Rail Car Movement Simulator — frontend */

// ── State ─────────────────────────────────────────────────────────────────────
let locations = [];
let industries = [];
let cars = [];
let waybillPool = [];
let commodityMap = [];
let carTypes = [];
let selectedCarId = null;
let editingWaybillId = null;
let photoPath = null;
let stagingMergeDeleteId = null;
let switchingAreas = [];
let dispatchPlans = [];
let opsMode = "free";
let settings = null;

// ── Fast clock ────────────────────────────────────────────────────────────────
let clockInterval = null;
let clockState = null;
let _clockEventSource = null;

function _applyClockState(state) {
  clockState = state;
  clearInterval(clockInterval);
  clockInterval = null;
  if (state?.started_at) {
    clockInterval = setInterval(updateClock, 1000);
    updateClock();
  } else {
    const el = $("#clock-time");
    if (el) el.textContent = "--:--";
  }
  const btn = $("#btn-clock-pause");
  if (btn) btn.textContent = state?.paused_at ? "▶" : "⏸";
}

function _openClockEventSource() {
  if (_clockEventSource) return;
  _clockEventSource = new EventSource("/api/session/clock/events");
  _clockEventSource.onmessage = e => {
    try { _applyClockState(JSON.parse(e.data)); } catch {}
  };
  _clockEventSource.onerror = () => {
    _clockEventSource.close();
    _clockEventSource = null;
    setTimeout(_openClockEventSource, 5000);
  };
}

async function fetchAndStartClock() {
  const state = await api("GET", "/api/session/clock");
  _applyClockState(state);
  _openClockEventSource();
}

function startClockTick() {
  clearInterval(clockInterval);
  clockInterval = setInterval(updateClock, 1000);
  updateClock();
}

function updateClock() {
  if (!clockState?.started_at) return;
  const { start_time, speed, started_at, paused_at, paused_accum_s } = clockState;
  if (paused_at) return;
  const elapsedRealS = Date.now() / 1000 - started_at - paused_accum_s;
  const [h, m] = start_time.split(":").map(Number);
  const startMin = h * 60 + m;
  const modelMin = (startMin + Math.floor(elapsedRealS * speed / 60)) % (24 * 60);
  const dh = String(Math.floor(modelMin / 60)).padStart(2, "0");
  const dm = String(modelMin % 60).padStart(2, "0");
  const el = $("#clock-time");
  if (el) el.textContent = `${dh}:${dm}`;
}

function stopClock() {
  clearInterval(clockInterval);
  clockInterval = null;
  clockState = null;
}

async function toggleClockPause() {
  if (!clockState) return;
  const endpoint = clockState.paused_at ? "/api/session/clock/resume" : "/api/session/clock/pause";
  const state = await api("POST", endpoint);
  _applyClockState(state); // immediate update for this tab; SSE will sync others
}

// ── Helpers ───────────────────────────────────────────────────────────────────
const $ = (sel, ctx = document) => ctx.querySelector(sel);
const $$ = (sel, ctx = document) => [...ctx.querySelectorAll(sel)];

function _authToken() {
  return sessionStorage.getItem("waypoint_token") || "";
}

// Returns a usable <img src> value from a photo_path (local path or CDN URL)
// and optional pre-computed photo_url from the API.
function photoSrc(path, url) {
  if (url) return url;
  if (!path) return "";
  if (path.startsWith("http")) return path;
  return "/" + path;
}

async function api(method, path, body) {
  const opts = { method, headers: {} };
  const token = _authToken();
  if (token) opts.headers["Authorization"] = `Bearer ${token}`;
  if (body && !(body instanceof FormData)) {
    opts.headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(body);
  } else if (body) {
    opts.body = body;
  }
  const res = await fetch(path, opts);
  if (res.status === 401) {
    // Token missing or expired — redirect to login if a Supabase login URL is configured
    const loginUrl = document.querySelector("meta[name=supabase-login-url]")?.content;
    if (loginUrl) { window.location.href = loginUrl; return; }
  }
  if (res.status === 204) return null;
  let data;
  try {
    data = await res.json();
  } catch {
    throw new Error(`Server error (${res.status})`);
  }
  if (!res.ok) { const err = new Error(data.detail || "Request failed"); err.status = res.status; throw err; }
  return data;
}

function hide(el) { el.classList.add("hidden"); }
function show(el) { el.classList.remove("hidden"); }

function showToast(message, type = "info", duration = 3500) {
  const openDialog = document.querySelector("dialog[open]");
  const container = openDialog
    ? (openDialog.querySelector(".dialog-toast-container") || (() => {
        const c = document.createElement("div");
        c.className = "dialog-toast-container";
        openDialog.querySelector("article").appendChild(c);
        return c;
      })())
    : $("#toast-container");
  const toast = document.createElement("div");
  toast.className = `toast ${type}`;
  toast.textContent = message;
  container.appendChild(toast);
  requestAnimationFrame(() => { requestAnimationFrame(() => toast.classList.add("show")); });
  setTimeout(() => {
    toast.classList.remove("show");
    toast.addEventListener("transitionend", () => toast.remove(), { once: true });
  }, duration);
}

function emptyState(icon, message) {
  return `<div class="empty-state"><span class="empty-state-icon">${icon}</span><p>${message}</p></div>`;
}

function withLoading(btn, label, fn) {
  const orig = btn.innerHTML;
  btn.disabled = true;
  btn.innerHTML = `<span class="spinner"></span>${label}`;
  return fn().finally(() => {
    btn.disabled = false;
    btn.innerHTML = orig;
  });
}

// ── Photo library ─────────────────────────────────────────────────────────────
let photoLibraryCallback = null;
let selectedLibraryPaths = new Set();

function updateDeleteSelectedBtn() {
  const btn = $("#btn-delete-selected");
  const n = selectedLibraryPaths.size;
  if (n > 0) {
    show(btn);
    $("#selected-count").textContent = n;
  } else {
    hide(btn);
    delete btn.dataset.confirm;
    btn.classList.remove("btn-confirming");
  }
}

async function refreshLibraryGrid() {
  const grid = $("#photo-library-grid");
  grid.innerHTML = `<p class="muted" style="text-align:center;padding:1rem"><span class="spinner"></span>Loading…</p>`;
  try {
    const files = await api("GET", "/api/uploads");
    if (!files.length) {
      grid.innerHTML = emptyState("🖼", "No photos uploaded yet.");
    } else {
      grid.innerHTML = files.map(f => {
        const sel = selectedLibraryPaths.has(f.path) ? " lib-selected" : "";
        const badge = f.is_default
          ? '<span class="lib-badge lib-badge-default">default</span>'
          : f.assigned
            ? '<span class="lib-badge">in use</span>'
            : "";
        return `
        <div class="lib-thumb${f.assigned ? " lib-assigned" : ""}${sel}"
             data-path="${f.path}" data-url="${f.url}" data-is-default="${f.is_default}">
          <img src="${f.url}" alt="" loading="lazy" />
          ${badge}
        </div>`;
      }).join("");
      $$(".lib-thumb").forEach(el => {
        el.addEventListener("click", () => {
          if (photoLibraryCallback) {
            photoLibraryCallback({ path: el.dataset.path, url: el.dataset.url });
            $("#photo-library-dialog").close();
            return;
          }
          // selection mode — default images cannot be selected for deletion
          if (el.dataset.isDefault === "true") return;
          if (selectedLibraryPaths.has(el.dataset.path)) {
            selectedLibraryPaths.delete(el.dataset.path);
            el.classList.remove("lib-selected");
          } else {
            selectedLibraryPaths.add(el.dataset.path);
            el.classList.add("lib-selected");
          }
          updateDeleteSelectedBtn();
        });
      });
    }
  } catch (err) {
    grid.innerHTML = `<p class="muted" style="text-align:center">Failed to load library: ${err.message}</p>`;
  }
  updateDeleteSelectedBtn();
}

async function openPhotoLibrary(onSelect) {
  photoLibraryCallback = onSelect;
  selectedLibraryPaths.clear();
  $("#photo-library-dialog").showModal();
  await refreshLibraryGrid();
}

$("#btn-close-library").addEventListener("click", () => {
  selectedLibraryPaths.clear();
  updateDeleteSelectedBtn();
  $("#photo-library-dialog").close();
});

$("#btn-delete-selected").addEventListener("click", async () => {
  const btn = $("#btn-delete-selected");
  if (!btn.dataset.confirm) {
    btn.dataset.confirm = "1";
    btn.classList.add("btn-confirming");
    const orig = btn.innerHTML;
    btn.textContent = `⚠ Delete ${selectedLibraryPaths.size}? Click again.`;
    setTimeout(() => {
      if (btn.dataset.confirm) {
        delete btn.dataset.confirm;
        btn.classList.remove("btn-confirming");
        btn.innerHTML = orig;
      }
    }, 4000);
    return;
  }
  delete btn.dataset.confirm;
  btn.classList.remove("btn-confirming");
  try {
    const result = await api("POST", "/api/uploads/delete-many", { paths: [...selectedLibraryPaths] });
    selectedLibraryPaths.clear();
    const msg = result.protected
      ? `Deleted ${result.deleted}, skipped ${result.protected} in-use image(s).`
      : `Deleted ${result.deleted} image(s).`;
    showToast(msg, result.protected ? "warning" : "success");
    await refreshLibraryGrid();
  } catch (err) {
    showToast("Delete failed: " + err.message, "error");
  }
});

$("#btn-library-upload").addEventListener("click", () => $("#library-upload-input").click());
$("#library-upload-input").addEventListener("change", async e => {
  const files = Array.from(e.target.files);
  if (!files.length) return;
  const btn = $("#btn-library-upload");
  btn.disabled = true;
  let failed = 0;
  for (let i = 0; i < files.length; i++) {
    btn.textContent = `Uploading ${i + 1}/${files.length}…`;
    try {
      const fd = new FormData();
      fd.append("file", files[i]);
      const token = _authToken();
      const resp = await fetch("/api/cars/upload?skip_analysis=true", {
        method: "POST", body: fd,
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      });
      if (!resp.ok) throw new Error(await resp.text());
    } catch {
      failed++;
    }
  }
  btn.textContent = "⬆ Load File(s)";
  btn.disabled = false;
  e.target.value = "";
  if (failed) showToast(`${failed} file(s) failed to upload.`, "error");
  await refreshLibraryGrid();
});

// ── Clock bar (always-visible in ops tab) ─────────────────────────────────────
$("#btn-clock-pause").addEventListener("click", toggleClockPause);
$("#btn-clock-reset").addEventListener("click", async () => {
  const state = await api("POST", "/api/session/clock/start");
  _applyClockState(state); // immediate update for this tab; SSE will sync others
});

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
    $$(".tab-link").forEach(l => l.classList.remove("active"));
    $$(".tab-panel").forEach(p => p.classList.add("hidden"));
    link.classList.add("active");
    $(`#tab-${tab}`).classList.remove("hidden");
    if (navCurrentTab) navCurrentTab.textContent = link.textContent.trim();
    if (tab === "operations") loadOperations();
    if (tab === "waybills") loadWaybillPool();
    if (tab === "layout") loadLayout();
    if (tab === "settings") loadSettings();
  });
});

// ── Roster ────────────────────────────────────────────────────────────────────
async function loadRoster() {
  cars = await api("GET", "/api/cars");
  renderCarGrid();
}

function defaultCarImage(carTypeName) {
  const ct = carTypes.find(t => t.name === carTypeName);
  return ct?.default_photo_path ? `/${ct.default_photo_path}` : null;
}

function carCardHTML(car) {
  const needsMove = car.active_waybill
    && car.active_waybill.destination_id != null
    && car.current_location_id !== car.active_waybill.destination_id;
  const defImg = defaultCarImage(car.car_type);
  return `
    <div class="car-card${needsMove ? ' car-needs-move' : ''}" data-id="${car.id}">
      <div class="car-thumb">
        ${car.photo_path
          ? `<img src="${photoSrc(car.photo_path, car.photo_url)}" alt="${car.reporting_marks} ${car.car_number}" />`
          : defImg
            ? `<img src="${defImg}" alt="${car.car_type}" class="default-car-img" />`
            : `<div class="no-photo">${car.car_type}</div>`}
      </div>
      <div class="car-info">
        <strong>${car.reporting_marks || "—"} ${car.car_number || ""}</strong>
        <span class="car-type">${car.car_type}</span>
        <span class="car-color">${car.color}</span>
        <span class="car-location">${car.current_location_name || "No location"}</span>
        ${car.active_waybill
          ? `<span class="waybill-badge">${car.active_waybill.is_empty ? "Empty" : car.active_waybill.commodity || "Loaded"} → ${car.active_waybill.destination_name || "?"}</span>`
          : `<span class="waybill-badge muted">No waybill</span>`}
      </div>
    </div>
  `;
}

function renderPowerStrip(power, caboose, editable = false) {
  const locos = power || [];
  function powerThumb(c) {
    const img = c.photo_path ? photoSrc(c.photo_path, c.photo_url) : defaultCarImage(c.car_type);
    return img
      ? `<img src="${img}" alt="${c.car_type}" />`
      : `<span style="font-size:0.65rem">${c.car_type}</span>`;
  }
  function powerChip(c, label) {
    const removeBtn = editable
      ? `<button class="power-chip-remove" data-remove-id="${c.id}" data-remove-type="${label}" title="Remove">✕</button>`
      : "";
    return `<div class="power-chip" title="${label}">
      ${powerThumb(c)}
      <span class="power-chip-marks">${c.reporting_marks || "—"} ${c.car_number || ""}</span>
      ${removeBtn}
    </div>`;
  }
  const locoChips   = locos.map(c => powerChip(c, "locomotive")).join("");
  const cabooseChip = caboose ? powerChip(caboose, "caboose") : "";
  const content = locoChips || cabooseChip
    ? `${locoChips}${locoChips && cabooseChip ? '<span class="power-strip-sep">·</span>' : ""}${cabooseChip}`
    : `<span class="power-strip-empty">No power assigned</span>`;
  return `<div class="session-power-strip">
    <span class="muted small" style="margin-right:0.5rem">Power:</span>
    ${content}
  </div>`;
}

function renderCarGrid() {
  const locos   = cars.filter(c => c.car_type === "locomotive");
  const freight = cars.filter(c => c.car_type !== "locomotive");

  const poolSection  = $("#power-pool-section");
  const poolBody     = $("#power-pool-body");
  const poolList     = $("#power-pool-list");
  const poolDivider  = $("#power-pool-divider");
  const grid         = $("#car-grid");

  if (locos.length) {
    poolList.innerHTML = locos.map(carCardHTML).join("");
    show(poolSection);
    show(poolDivider);
  } else {
    hide(poolSection);
    hide(poolDivider);
  }

  if (!freight.length && !locos.length) {
    grid.innerHTML = emptyState("🚃", "No cars yet — add one with the buttons above.");
  } else if (!freight.length) {
    grid.innerHTML = "";
  } else {
    grid.innerHTML = freight.map(carCardHTML).join("");
  }

  $$(".car-card").forEach(card => {
    card.addEventListener("click", () => openCarDetail(parseInt(card.dataset.id)));
  });

  checkOrphanedCars();
}

function checkOrphanedCars() {
  const orphaned = cars.filter(c => c.current_location_id && !c.current_location_name);
  const banner = $("#orphaned-cars-banner");
  const badge  = $("#roster-badge");
  const msg    = $("#orphaned-cars-msg");
  if (orphaned.length) {
    const n = orphaned.length;
    msg.textContent = `⚠ ${n} car${n !== 1 ? "s have" : " has"} an invalid location and may not display correctly.`;
    show(banner);
    badge.textContent = n;
    show(badge);
  } else {
    hide(banner);
    hide(badge);
  }
}

$("#btn-repair-cars").addEventListener("click", async () => {
  try {
    const result = await api("POST", "/api/cars/repair");
    cars = await api("GET", "/api/cars");
    renderCarGrid();
    showToast(`Repaired ${result.repaired} car${result.repaired !== 1 ? "s" : ""}.`, "success");
  } catch (err) {
    showToast("Repair failed: " + err.message, "error");
  }
});

$("#btn-toggle-power-pool").addEventListener("click", () => {
  const body = $("#power-pool-body");
  const btn  = $("#btn-toggle-power-pool");
  if (body.classList.contains("hidden")) {
    show(body);
    btn.textContent = "▼";
  } else {
    hide(body);
    btn.textContent = "▶";
  }
});

$("#btn-toggle-dispatcher").addEventListener("click", () => {
  const body = $("#dispatcher-body");
  const btn  = $("#btn-toggle-dispatcher");
  if (body.classList.contains("hidden")) {
    show(body);
    btn.textContent = "▼";
  } else {
    hide(body);
    btn.textContent = "▶";
  }
});

$("#btn-toggle-ops").addEventListener("click", () => {
  const body = $("#ops-body");
  const btn  = $("#btn-toggle-ops");
  if (body.classList.contains("hidden")) {
    show(body);
    btn.textContent = "▼";
  } else {
    hide(body);
    btn.textContent = "▶";
  }
});

$("#btn-toggle-freight-cars").addEventListener("click", () => {
  const body = $("#freight-cars-body");
  const btn  = $("#btn-toggle-freight-cars");
  if (body.classList.contains("hidden")) {
    show(body);
    btn.textContent = "▼";
  } else {
    hide(body);
    btn.textContent = "▶";
  }
});

$("#btn-toggle-locations").addEventListener("click", () => {
  const body = $("#location-body");
  const btn  = $("#btn-toggle-locations");
  if (body.classList.contains("hidden")) {
    show(body);
    btn.textContent = "▼";
  } else {
    hide(body);
    btn.textContent = "▶";
  }
});

$("#btn-toggle-industries").addEventListener("click", () => {
  const body = $("#industries-body");
  const btn  = $("#btn-toggle-industries");
  if (body.classList.contains("hidden")) {
    show(body);
    btn.textContent = "▼";
  } else {
    hide(body);
    btn.textContent = "▶";
  }
});

// ── Add car via photo ─────────────────────────────────────────────────────────
let addMode = "photo"; // "photo" | "manual"
let stylizedPath = null;
let stylizeQuotaExceeded = false;

function showStylizeIdle() {
  show($("#stylize-idle"));
  hide($("#stylize-processing"));
  hide($("#stylize-result"));
  hide($("#stylize-error"));
}

function _applyStylizeQuotaUI() {
  const btn = $("#btn-stylize");
  if (!btn) return;
  btn.disabled = true;
  btn.title = "Image generation requires a paid Gemini API key";
  updateDefaultImageOffer();
}

async function runStylize() {
  if (stylizeQuotaExceeded) return;
  hide($("#stylize-idle"));
  hide($("#stylize-result"));
  hide($("#stylize-error"));
  show($("#stylize-processing"));
  try {
    const result = await api("POST", "/api/cars/stylize", { photo_path: photoPath });
    stylizedPath = result.stylized_path;
    $("#stylize-preview").src = result.url;
    hide($("#stylize-processing"));
    show($("#stylize-result"));
  } catch (err) {
    hide($("#stylize-processing"));
    if (err.status === 402) {
      stylizeQuotaExceeded = true;
      $("#stylize-error-msg").textContent = err.message;
      show($("#stylize-error"));
      show($("#stylize-idle"));
      _applyStylizeQuotaUI();
    } else {
      $("#stylize-error-msg").textContent = "Stylize failed: " + err.message;
      show($("#stylize-error"));
      show($("#stylize-idle"));
    }
  }
}

$("#btn-add-car").addEventListener("click", () => {
  addMode = "photo";
  show($("#add-car-form"));
  show($("#upload-zone"));
  hide($("#car-fields"));
  hide($("#upload-preview"));
  hide($("#analyzing-msg"));
  hide($("#vision-error"));
  hide($("#stylize-section"));
  stylizedPath = null;
  photoPath = null;
  $("#photo-input").value = "";
  $("#upload-label").textContent = "📷 Click or drop a photo of the car";
});

$("#btn-add-manual").addEventListener("click", () => {
  addMode = "manual";
  show($("#add-car-form"));
  show($("#upload-zone"));
  hide($("#upload-preview"));
  hide($("#analyzing-msg"));
  hide($("#vision-error"));
  hide($("#default-image-offer"));
  show($("#car-fields"));
  photoPath = null;
  $("#photo-input").value = "";
  $("#upload-label").textContent = "📷 Click or drop a photo (optional)";
  $("#field-marks").value = "";
  $("#field-number").value = "";
  $("#field-type").value = "other";
  $("#field-color").value = "";
  updateDefaultImageOffer();
});

$("#btn-cancel-car").addEventListener("click", async () => {
  await discardStylized();
  hide($("#add-car-form"));
  hide($("#stylize-section"));
  hide($("#default-image-offer"));
});

function applyAnalysis(result) {
  if (result.photo_path) photoPath = result.photo_path;
  $("#field-marks").value = result.reporting_marks || "";
  $("#field-number").value = result.car_number || "";
  $("#field-type").value  = result.car_type || "other";
  $("#field-color").value = result.color || "";
  if (result._error) {
    $("#vision-error-msg").textContent =
      "Vision analysis failed — please fill in details manually. (" + result._error + ")";
    show($("#vision-error"));
  } else {
    hide($("#vision-error"));
  }
  hide($("#analyzing-msg"));
  show($("#car-fields"));
  if (addMode === "photo") {
    stylizedPath = null;
    showStylizeIdle();
    show($("#stylize-section"));
    if (stylizeQuotaExceeded) _applyStylizeQuotaUI();
  }
}

// ── Stylize handlers ──────────────────────────────────────────────────────────
async function discardStylized() {
  if (!stylizedPath) return;
  const path = stylizedPath;
  stylizedPath = null;
  try { await api("POST", "/api/uploads/delete", { path }); } catch { /* best-effort */ }
}

$("#btn-stylize").addEventListener("click", runStylize);

$("#btn-regenerate").addEventListener("click", async () => {
  await discardStylized();
  runStylize();
});

$("#btn-use-stylized").addEventListener("click", () => {
  if (stylizedPath) {
    photoPath = stylizedPath;
    $("#preview-img").src = $("#stylize-preview").src;
  }
  stylizedPath = null;
  hide($("#stylize-section"));
});

$("#btn-keep-original").addEventListener("click", async () => {
  await discardStylized();
  hide($("#stylize-section"));
});

// Library → add car (shared button; branches on addMode)
$("#btn-library-add").addEventListener("click", () => {
  if (addMode === "manual") {
    // Manual mode: just set photo, no analysis
    openPhotoLibrary(({ path, url }) => {
      photoPath = path;
      $("#preview-img").src = url;
      show($("#upload-preview"));
      hide($("#default-image-offer"));
    });
  } else {
    // Photo mode: run vision analysis on selection
    openPhotoLibrary(async ({ path, url }) => {
      $("#preview-img").src = url;
      show($("#upload-preview"));
      hide($("#car-fields"));
      show($("#analyzing-msg"));
      hide($("#vision-error"));
      photoPath = path;
      try {
        const result = await api("POST", "/api/cars/analyze-photo", { photo_path: path });
        applyAnalysis(result);
      } catch (err) {
        $("#vision-error-msg").textContent = "Analysis failed: " + err.message;
        show($("#vision-error"));
        show($("#car-fields"));
        hide($("#analyzing-msg"));
      }
    });
  }
});

function isBrowserUnsupportedImage(file) {
  const ext = file.name.split(".").pop().toLowerCase();
  return ["heic", "heif"].includes(ext) || file.type === "image/heic" || file.type === "image/heif";
}

async function processPhotoFile(file) {
  if (!file) return;

  $("#upload-label").textContent = file.name;
  hide($("#vision-error"));

  const unsupported = isBrowserUnsupportedImage(file);
  if (!unsupported) {
    $("#preview-img").src = URL.createObjectURL(file);
    show($("#upload-preview"));
  }

  const form = new FormData();
  form.append("file", file);

  if (addMode === "manual") {
    try {
      const result = await api("POST", "/api/cars/upload", form);
      if (result.photo_path) {
        photoPath = result.photo_path;
        $("#preview-img").src = photoSrc(result.photo_path);
        show($("#upload-preview"));
      }
      hide($("#default-image-offer"));
    } catch (err) {
      $("#vision-error-msg").textContent = "Upload failed: " + err.message;
      show($("#vision-error"));
    }
    return;
  }

  hide($("#car-fields"));
  show($("#analyzing-msg"));
  try {
    const result = await api("POST", "/api/cars/upload", form);
    if (result.photo_path) {
      $("#preview-img").src = photoSrc(result.photo_path);
      show($("#upload-preview"));
    }
    applyAnalysis(result);
  } catch (err) {
    hide($("#analyzing-msg"));
    $("#vision-error-msg").textContent = "Upload failed: " + err.message;
    show($("#vision-error"));
    show($("#car-fields"));
  }
}

$("#photo-input").addEventListener("change", e => processPhotoFile(e.target.files[0]));

$("#upload-zone").addEventListener("dragover", e => { e.preventDefault(); e.dataTransfer.dropEffect = "copy"; });
$("#upload-zone").addEventListener("drop", e => { e.preventDefault(); processPhotoFile(e.dataTransfer.files[0]); });

$("#btn-retry-vision").addEventListener("click", async () => {
  hide($("#vision-error"));
  hide($("#car-fields"));
  show($("#analyzing-msg"));
  try {
    const result = await api("POST", "/api/cars/analyze-photo", { photo_path: photoPath });
    applyAnalysis(result);
  } catch (err) {
    $("#vision-error-msg").textContent = "Retry failed: " + err.message;
    show($("#vision-error"));
    show($("#car-fields"));
    hide($("#analyzing-msg"));
  }
});

$("#btn-save-car").addEventListener("click", async () => {
  const body = {
    car_type: $("#field-type").value,
    color: $("#field-color").value.trim(),
    car_number: $("#field-number").value.trim(),
    reporting_marks: $("#field-marks").value.trim(),
    photo_path: photoPath || "",
  };
  const btn = $("#btn-save-car");
  try {
    await withLoading(btn, "Saving…", async () => {
      await api("POST", "/api/cars", body);
      hide($("#add-car-form"));
      await loadRoster();
      showToast("Car saved.", "success");
    });
  } catch (err) {
    showToast("Error saving car: " + err.message, "error");
  }
});

// ── Car detail dialog ─────────────────────────────────────────────────────────
async function openCarDetail(carId) {
  selectedCarId = carId;
  const car = cars.find(c => c.id === carId);
  if (!car) return;

  $("#detail-title").textContent = `${car.reporting_marks || "—"} ${car.car_number || ""}  (${car.car_type})`;

  const waybills = await api("GET", `/api/cars/${carId}/waybills`);
  const activeSlot = car.active_waybill_slot;

  const wbHtml = waybills.length
    ? waybills.map(w => `
        <div class="waybill-row ${w.slot_index === activeSlot ? "active-slot" : ""}">
          <span class="slot-num">${w.slot_index + 1}</span>
          <span><strong>${w.name || (w.is_empty ? "EMPTY" : (w.commodity || "Loaded"))}</strong></span>
          <span>${w.origin_name || "?"} → ${w.destination_name || "?"}</span>
          ${w.industry_name ? `<span class="industry-tag">${w.industry_name}</span>` : ""}
        </div>
      `).join("")
    : "<p class='muted'>No waybill cards yet. Click Edit Waybills to assign from the pool.</p>";

  const detailDefImg = defaultCarImage(car.car_type);
  $("#detail-body").innerHTML = `
    <div class="detail-grid">
      ${car.photo_path
        ? `<img src="${photoSrc(car.photo_path, car.photo_url)}" class="detail-photo" />`
        : detailDefImg
          ? `<img src="${detailDefImg}" class="detail-photo default-car-img" />`
          : ""}
      <div>
        <p><strong>Type:</strong> ${car.car_type}</p>
        <p><strong>Color:</strong> ${car.color || "—"}</p>
        <p><strong>Location:</strong> ${car.current_location_name || "Unassigned"}</p>
        <p><strong>Active Slot:</strong> ${activeSlot + 1} of ${Math.max(waybills.length, 1)}</p>
      </div>
    </div>
    <h5>Waybill Cards</h5>
    <div class="waybill-list">${wbHtml}</div>
  `;

  hide($("#detail-error"));
  $("#car-detail-dialog").showModal();
}

$("#close-detail-dialog").addEventListener("click", () => $("#car-detail-dialog").close());

$("#btn-advance-waybill").addEventListener("click", async () => {
  if (!selectedCarId) return;
  const btn = $("#btn-advance-waybill");
  try {
    await withLoading(btn, "Advancing…", async () => {
      const updated = await api("POST", `/api/cars/${selectedCarId}/advance`);
      const idx = cars.findIndex(c => c.id === selectedCarId);
      if (idx !== -1) cars[idx] = updated;
      renderCarGrid();
      await openCarDetail(selectedCarId);
    });
  } catch (err) {
    showToast("Error: " + err.message, "error");
  }
});

$("#btn-delete-car").addEventListener("click", async () => {
  if (!selectedCarId) return;
  const btn = $("#btn-delete-car");
  if (!btn.dataset.confirm) {
    btn.dataset.confirm = "1";
    btn.classList.add("btn-confirming");
    const orig = btn.textContent;
    btn.textContent = "Confirm delete?";
    setTimeout(() => { delete btn.dataset.confirm; btn.classList.remove("btn-confirming"); btn.textContent = orig; }, 3000);
    return;
  }
  btn.classList.remove("btn-confirming");
  delete btn.dataset.confirm;
  try {
    await api("DELETE", `/api/cars/${selectedCarId}`);
    $("#car-detail-dialog").close();
    await loadRoster();
    showToast("Car deleted.", "warn");
  } catch (err) {
    const errEl = $("#detail-error");
    errEl.textContent = "Delete failed: " + err.message;
    show(errEl);
    btn.textContent = "Delete Car";
  }
});

// ── Edit car dialog ───────────────────────────────────────────────────────────
$("#btn-edit-car").addEventListener("click", () => {
  const car = cars.find(c => c.id === selectedCarId);
  if (!car) return;
  $("#edit-field-marks").value = car.reporting_marks || "";
  $("#edit-field-number").value = car.car_number || "";
  $("#edit-field-type").value = car.car_type || "other";
  $("#edit-field-color").value = car.color || "";
  // photo section
  const preview = $("#edit-photo-preview");
  const btnText = $("#edit-photo-btn-text");
  $("#edit-photo-path").value = car.photo_path || "";
  if (car.photo_path) {
    preview.src = photoSrc(car.photo_path, car.photo_url);
    preview.style.display = "block";
    btnText.textContent = "📷 Upload Image";
  } else {
    preview.style.display = "none";
    btnText.textContent = "📷 Upload Image";
  }
  $("#edit-car-dialog").showModal();
});

$("#close-edit-car-dialog").addEventListener("click", () => $("#edit-car-dialog").close());
$("#btn-cancel-edit-car").addEventListener("click", () => $("#edit-car-dialog").close());

// Library → edit car context
$("#btn-library-edit").addEventListener("click", () => {
  openPhotoLibrary(({ path, url }) => {
    $("#edit-photo-path").value = path;
    const preview = $("#edit-photo-preview");
    preview.src = url;
    preview.style.display = "block";
    $("#edit-photo-btn-text").textContent = "📷 Upload Image";
  });
});

$("#edit-photo-input").addEventListener("change", async () => {
  const file = $("#edit-photo-input").files[0];
  if (!file) return;
  const btnText = $("#edit-photo-btn-text");
  btnText.textContent = "Uploading…";
  try {
    const fd = new FormData();
    fd.append("file", file);
    const token = _authToken();
    const result = await fetch("/api/cars/upload?skip_analysis=true", {
      method: "POST", body: fd,
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    }).then(r => r.json());
    if (result.photo_path) {
      $("#edit-photo-path").value = result.photo_path;
      const preview = $("#edit-photo-preview");
      preview.src = photoSrc(result.photo_path);
      preview.style.display = "block";
      btnText.textContent = "📷 Upload Image";
    } else {
      btnText.textContent = "📷 Upload Image";
    }
  } catch {
    btnText.textContent = "📷 Upload failed";
  }
});

$("#btn-save-edit-car").addEventListener("click", async () => {
  const btn = $("#btn-save-edit-car");
  try {
    await withLoading(btn, "Saving…", async () => {
      const body = {
        car_type: $("#edit-field-type").value,
        color: $("#edit-field-color").value.trim(),
        car_number: $("#edit-field-number").value.trim(),
        reporting_marks: $("#edit-field-marks").value.trim(),
      };
      const newPhoto = $("#edit-photo-path").value;
      if (newPhoto) body.photo_path = newPhoto;
      await api("PUT", `/api/cars/${selectedCarId}`, body);
      $("#edit-car-dialog").close();
      await loadRoster();
      await openCarDetail(selectedCarId);
      showToast("Car updated.", "success");
    });
  } catch (err) {
    showToast("Error saving car: " + err.message, "error");
  }
});

// ── Move car dialog ───────────────────────────────────────────────────────────
$("#btn-move-car").addEventListener("click", () => {
  const sel = $("#move-location-select");
  sel.innerHTML = '<option value="">— unassigned —</option>' +
    locations.map(l => `<option value="${l.id}">${l.name} (${l.location_type})</option>`).join("");
  const car = cars.find(c => c.id === selectedCarId);
  if (car?.current_location_id) sel.value = car.current_location_id;
  $("#move-car-dialog").showModal();
});

$("#close-move-dialog").addEventListener("click", () => $("#move-car-dialog").close());
$("#btn-cancel-move").addEventListener("click", () => $("#move-car-dialog").close());

$("#btn-confirm-move").addEventListener("click", async () => {
  const locId = $("#move-location-select").value;
  try {
    const updated = await api("PUT", `/api/cars/${selectedCarId}/location`, {
      location_id: locId ? parseInt(locId) : null,
    });
    const idx = cars.findIndex(c => c.id === selectedCarId);
    if (idx !== -1) cars[idx] = updated;
    renderCarGrid();
    await openCarDetail(selectedCarId);
    $("#move-car-dialog").close();
  } catch (err) {
    showToast("Error: " + err.message, "error");
  }
});

// ── Per-car auto-assign ───────────────────────────────────────────────────────

$("#btn-auto-assign-car").addEventListener("click", async () => {
  if (!selectedCarId) return;
  const btn = $("#btn-auto-assign-car");
  if (!btn.dataset.confirm) {
    btn.dataset.confirm = "1";
    btn.classList.add("btn-confirming");
    const orig = btn.textContent;
    btn.dataset.origText = orig;
    btn.textContent = "Clear & reassign?";
    setTimeout(() => {
      delete btn.dataset.confirm;
      delete btn.dataset.origText;
      btn.classList.remove("btn-confirming");
      btn.textContent = orig;
    }, 3000);
    return;
  }
  const orig = btn.dataset.origText || "🔄 Auto-Assign";
  btn.classList.remove("btn-confirming");
  delete btn.dataset.confirm;
  delete btn.dataset.origText;
  await withLoading(btn, "Assigning…", async () => {
    const result = await api("POST", `/api/cars/${selectedCarId}/auto-assign`);
    if (result.assigned === 0) {
      showToast("No matching waybills available for this car.", "warning");
    } else {
      showToast(`${result.assigned} waybill(s) assigned.`, "success");
    }
    await openCarDetail(selectedCarId);
  });
});

// ── Assign waybill slots dialog ───────────────────────────────────────────────
const SLOT_COUNT = 4;

function buildSlotOptions(expectedOriginId, carType, currentWaybillId) {
  const carTypeLower = (carType || "").toLowerCase();
  const wildcards = new Set(["", "all", "any"]);
  function typeMatches(w) {
    const req = (w.required_car_type || "").toLowerCase();
    return wildcards.has(req) || req === carTypeLower;
  }
  function originMatches(w) {
    if (!expectedOriginId) return true;
    if (!w.origin_id) return true;
    return w.origin_id === expectedOriginId;
  }
  function label(w) {
    return `${w.name || w.id}${w.origin_name ? ` (${w.origin_name} → ${w.destination_name || "?"})` : ""}`;
  }

  const current = waybillPool.filter(w => w.id === currentWaybillId);
  const primary  = waybillPool.filter(w => w.id !== currentWaybillId && typeMatches(w) && originMatches(w));
  const fallback = primary.length === 0
    ? waybillPool.filter(w => w.id !== currentWaybillId && typeMatches(w))
    : [];

  const opts = list => list.map(w => `<option value="${w.id}">${label(w)}</option>`).join("");

  return '<option value="">— empty —</option>' +
    opts(current) +
    opts(primary) +
    (fallback.length ? `<optgroup label="other locations">${opts(fallback)}</optgroup>` : "");
}

function getSelectedSlotWaybill(slotIndex) {
  const sel = $(`[data-slot="${slotIndex}"].slot-picker`, $("#waybill-slots"));
  return sel?.value ? waybillPool.find(w => w.id === parseInt(sel.value)) : null;
}

function refreshSlot(slotIndex, carType) {
  const sel = $(`[data-slot="${slotIndex}"].slot-picker`, $("#waybill-slots"));
  if (!sel) return;
  const currentVal = sel.value ? parseInt(sel.value) : null;
  const prevWb = slotIndex > 0 ? getSelectedSlotWaybill(slotIndex - 1) : null;
  const expectedOriginId = slotIndex === 0
    ? (cars.find(c => c.id === selectedCarId)?.current_location_id ?? null)
    : (prevWb?.destination_id ?? null);
  sel.innerHTML = buildSlotOptions(expectedOriginId, carType, currentVal);
  sel.value = currentVal || "";
}

$("#btn-edit-waybills").addEventListener("click", async () => {
  if (!selectedCarId) return;
  const car = cars.find(c => c.id === selectedCarId);
  const assigned = await api("GET", `/api/cars/${selectedCarId}/waybills`);
  const bySlot = {};
  assigned.forEach(w => { bySlot[w.slot_index] = w; });

  const activeSlot = car?.active_waybill_slot ?? 0;
  $("#waybill-dialog-title").textContent = `Assign Waybills — ${car?.reporting_marks || ""} ${car?.car_number || ""}`;

  $("#waybill-slots").innerHTML = Array.from({ length: SLOT_COUNT }, (_, i) => {
    return `
      <div class="slot-assign-row ${i === activeSlot ? "active-slot" : ""}">
        <span class="slot-num">${i + 1}${i === activeSlot ? " ★" : ""}</span>
        <select data-slot="${i}" class="slot-picker"></select>
      </div>
    `;
  }).join("");

  // Populate each slot with filtered options, pre-select current value
  for (let i = 0; i < SLOT_COUNT; i++) {
    refreshSlot(i, car?.car_type);
    if (bySlot[i]) {
      const sel = $(`[data-slot="${i}"].slot-picker`, $("#waybill-slots"));
      if (sel) sel.value = bySlot[i].id;
    }
    // Cascade: changing slot i re-filters slot i+1
    const sel = $(`[data-slot="${i}"].slot-picker`, $("#waybill-slots"));
    if (sel && i < SLOT_COUNT - 1) {
      sel.addEventListener("change", () => refreshSlot(i + 1, car?.car_type));
    }
  }

  $("#waybill-dialog").showModal();
});

$("#close-waybill-dialog").addEventListener("click", () => $("#waybill-dialog").close());
$("#btn-cancel-waybills").addEventListener("click", () => $("#waybill-dialog").close());

$("#btn-save-waybills").addEventListener("click", async () => {
  const slots = Array.from({ length: SLOT_COUNT }, (_, i) => {
    const sel = $(`[data-slot="${i}"].slot-picker`, $("#waybill-slots"));
    return { slot_index: i, waybill_id: sel?.value ? parseInt(sel.value) : null };
  });
  try {
    await api("PUT", `/api/cars/${selectedCarId}/slots`, { slots });
    const updated = await api("GET", "/api/cars");
    cars = updated;
    renderCarGrid();
    $("#waybill-dialog").close();
    await openCarDetail(selectedCarId);
  } catch (err) {
    showToast("Error saving waybills: " + err.message, "error");
  }
});

// ── Waybill pool ──────────────────────────────────────────────────────────────
async function loadWaybillPool() {
  waybillPool = await api("GET", "/api/waybills");
  renderWaybillPool();
}

function renderWaybillPool() {
  const list = $("#waybill-pool-list");
  if (!waybillPool.length) {
    list.innerHTML = emptyState("➡️", "No waybills yet — generate from industries or add one manually.");
    return;
  }
  list.innerHTML = waybillPool.map(w => `
    <div class="pool-item">
      <div class="pool-item-info">
        <strong>${w.name || "(unnamed)"}</strong>
        <span class="muted">${w.origin_name || "?"} → ${w.destination_name || "?"}</span>
        ${w.commodity ? `<span class="muted">${w.commodity}</span>` : ""}
        ${w.is_empty ? `<span class="muted">Empty move</span>` : ""}
        ${w.required_car_type ? `<span class="muted">Requires: ${w.required_car_type}</span>` : ""}
      </div>
      <div class="pool-item-meta">
        ${w.car_id ? `<span class="waybill-badge">${w.car_name || "Car"} · Slot ${w.slot_index + 1}</span>` : `<span class="waybill-badge muted">Unassigned</span>`}
      </div>
      <div class="pool-item-actions">
        <button class="outline small edit-wb" data-id="${w.id}">✏️</button>
        <button class="outline small contrast del-wb" data-id="${w.id}">🗑</button>
      </div>
    </div>
  `).join("");

  $$(".edit-wb").forEach(btn => {
    btn.addEventListener("click", () => openWaybillEditDialog(parseInt(btn.dataset.id)));
  });
  $$(".del-wb").forEach(btn => {
    btn.addEventListener("click", async () => {
      if (!btn.dataset.confirm) {
        btn.dataset.confirm = "1";
        btn.classList.add("btn-confirming");
        const orig = btn.innerHTML;
        btn.textContent = "Sure?";
        setTimeout(() => { delete btn.dataset.confirm; btn.classList.remove("btn-confirming"); btn.innerHTML = orig; }, 3000);
        return;
      }
      btn.classList.remove("btn-confirming");
      delete btn.dataset.confirm;
      try {
        await api("DELETE", `/api/waybills/${btn.dataset.id}`);
        await loadWaybillPool();
      } catch (err) {
        showToast("Error: " + err.message, "error");
      }
    });
  });
}

function openWaybillEditDialog(waybillId = null) {
  editingWaybillId = waybillId;
  const w = waybillId ? waybillPool.find(x => x.id === waybillId) : null;
  $("#waybill-edit-title").textContent = w ? "Edit Waybill" : "New Waybill";

  $("#we-name").value = w?.name || "";
  $("#we-commodity").value = w?.commodity || "";
  $("#we-empty").checked = w?.is_empty || false;

  const locOptions = '<option value="">—</option>' +
    locations.map(l => `<option value="${l.id}">${l.name}</option>`).join("");
  const indOptions = '<option value="">—</option>' +
    industries.map(i => `<option value="${i.id}">${i.name}</option>`).join("");

  $("#we-origin").innerHTML = locOptions;
  $("#we-destination").innerHTML = locOptions;
  $("#we-industry").innerHTML = indOptions;

  if (w?.origin_id) $("#we-origin").value = w.origin_id;
  if (w?.destination_id) $("#we-destination").value = w.destination_id;
  if (w?.industry_id) $("#we-industry").value = w.industry_id;
  $("#we-car-type").value = w?.required_car_type || "";

  $("#waybill-edit-dialog").showModal();
}

$("#btn-add-waybill").addEventListener("click", () => openWaybillEditDialog(null));
$("#close-waybill-edit-dialog").addEventListener("click", () => $("#waybill-edit-dialog").close());
$("#btn-cancel-waybill-edit").addEventListener("click", () => $("#waybill-edit-dialog").close());

// ── Generate waybills dialog ──────────────────────────────────────────────────
$("#btn-generate-waybills").addEventListener("click", () => {
  $("#generate-waybills-dialog").showModal();
});

$("#close-generate-dialog").addEventListener("click", () => $("#generate-waybills-dialog").close());
$("#btn-cancel-generate").addEventListener("click", () => $("#generate-waybills-dialog").close());

$("#btn-confirm-generate").addEventListener("click", async () => {
  const replace = document.querySelector('input[name="gen-mode"]:checked')?.value === "replace";
  const btn = $("#btn-confirm-generate");
  if (replace && !btn.dataset.confirm) {
    btn.dataset.confirm = "1";
    btn.classList.add("btn-confirming");
    const orig = btn.textContent;
    btn.textContent = "Replace all — confirm?";
    setTimeout(() => { delete btn.dataset.confirm; btn.classList.remove("btn-confirming"); btn.textContent = orig; }, 4000);
    return;
  }
  btn.classList.remove("btn-confirming");
  delete btn.dataset.confirm;
  try {
    await withLoading(btn, "Generating…", async () => {
      const result = await api("POST", "/api/generate-waybills", { replace });
      $("#generate-waybills-dialog").close();
      showToast(`Created ${result.created} waybill${result.created !== 1 ? "s" : ""}, skipped ${result.skipped}.`, "success");
      await loadWaybillPool();
    });
  } catch (err) {
    showToast("Error generating waybills: " + err.message, "error");
  }
});

// ── Auto-assign waybills ──────────────────────────────────────────────────────
$("#btn-auto-assign").addEventListener("click", async () => {
  const btn = $("#btn-auto-assign");
  try {
    await withLoading(btn, "Assigning…", async () => {
      const result = await api("POST", "/api/auto-assign-waybills");
      showToast(`Assigned ${result.assigned} waybill${result.assigned !== 1 ? "s" : ""} to cars.`, "success");
      cars = result.cars_updated;
      renderCarGrid();
      await loadWaybillPool();
    });
  } catch (err) {
    showToast("Error during auto-assign: " + err.message, "error");
  }
});

$("#btn-save-waybill-edit").addEventListener("click", async () => {
  const body = {
    name: $("#we-name").value.trim(),
    origin_id: $("#we-origin").value ? parseInt($("#we-origin").value) : null,
    destination_id: $("#we-destination").value ? parseInt($("#we-destination").value) : null,
    industry_id: $("#we-industry").value ? parseInt($("#we-industry").value) : null,
    commodity: $("#we-commodity").value.trim(),
    is_empty: $("#we-empty").checked,
    required_car_type: $("#we-car-type").value || null,
  };
  try {
    if (editingWaybillId) {
      await api("PUT", `/api/waybills/${editingWaybillId}`, body);
    } else {
      await api("POST", "/api/waybills", body);
    }
    $("#waybill-edit-dialog").close();
    await loadWaybillPool();
  } catch (err) {
    showToast("Error saving waybill: " + err.message, "error");
  }
});

// ── Operations view ───────────────────────────────────────────────────────────
async function loadOperations() {
  loadSessionFromStorage();

  // Layout Status strip — always visible
  await renderLayoutStatus();

  // Dispatcher always visible
  if (!locations.length || !switchingAreas.length) {
    [locations, switchingAreas] = await Promise.all([
      api("GET", "/api/locations"),
      api("GET", "/api/switching-areas"),
    ]);
  }
  if (!settings) {
    settings = await api("GET", "/api/settings");
    opsMode = settings?.ops_mode || "free";
  }
  await loadDispatcherPanel();
  show($("#dispatcher-panel"));

  fetchAndStartClock();

  if (session) {
    $("#ops-header-buttons").innerHTML = ""; // cleared by renderActiveSession
    renderActiveSession();
    return;
  }

  $("#ops-title").textContent = "Quick Op Session";
  // Idle state: "Plan Session" as fallback below the dispatcher
  $("#ops-header-buttons").innerHTML =
    `<button id="btn-plan-session">Start Quick Op Session</button>`;
  document.getElementById("btn-plan-session").addEventListener("click", async () => {
    const btn = document.getElementById("btn-plan-session");
    await withLoading(btn, "Planning…", async () => {
      try {
        const plan = await api("POST", "/api/session/plan");
        session = {
          warnings: plan.warnings || [],
          cars: [
            ...plan.arrivals.map(c => ({
              id: c.id,
              marks: `${c.reporting_marks || "—"} ${c.car_number || ""}`.trim(),
              carType: c.car_type,
              fromLocation: c.session_from_location_name,
              toLocation: c.session_to_location_name,
              photoPath: c.photo_path || null,
              photoUrl: c.photo_url || null,
              industryName: c.active_waybill?.industry_name || null,
              toIndustryId: c.active_waybill?.industry_id ?? null,
              cpSessions: c.cp_session_count || 0,
              priority: Math.floor(Math.random() * 1000),
              group: "arrivals",
              status: "pending",
            })),
            ...plan.departures.map(c => ({
              id: c.id,
              marks: `${c.reporting_marks || "—"} ${c.car_number || ""}`.trim(),
              carType: c.car_type,
              fromLocation: c.session_from_location_name,
              toLocation: c.session_to_location_name,
              photoPath: c.photo_path || null,
              photoUrl: c.photo_url || null,
              industryName: c.active_waybill?.industry_name || null,
              toIndustryId: null,
              cpSessions: 0,
              priority: 0,
              group: "departures",
              status: "pending",
            })),
            ...(plan.spots || []).map(c => ({
              id: c.id,
              marks: `${c.reporting_marks || "—"} ${c.car_number || ""}`.trim(),
              carType: c.car_type,
              fromLocation: c.session_from_location_name,
              toLocation: c.session_to_location_name,
              photoPath: c.photo_path || null,
              photoUrl: c.photo_url || null,
              industryName: c.active_waybill?.industry_name || null,
              toIndustryId: c.active_waybill?.industry_id ?? null,
              cpSessions: c.cp_session_count || 0,
              priority: Math.floor(Math.random() * 1000),
              group: "spots",
              status: "pending",
            })),
          ],
        };
        saveSession();
        renderActiveSession();
      } catch (err) {
        showToast("Error planning session: " + err.message, "error");
      }
    });
  });

  hide($("#session-warnings"));

  const ops = await api("GET", "/api/operations");
  const list = $("#ops-list");
  if (!ops.length) {
    list.innerHTML = emptyState("🚂", "No cars in the system yet — add some from the Car Roster tab.");
    return;
  }
  list.innerHTML = ops.map(car => {
    const wb = car.active_waybill;
    const needsMove = wb
      && wb.destination_id != null
      && car.current_location_id !== wb.destination_id;
    const dest = wb?.destination_name;
    const opsDefImg = defaultCarImage(car.car_type);
    const thumb = car.photo_path
      ? `<div class="session-car-thumb clickable-thumb" data-id="${car.id}"><img src="${photoSrc(car.photo_path, car.photo_url)}" alt="" /></div>`
      : opsDefImg
        ? `<div class="session-car-thumb clickable-thumb" data-id="${car.id}"><img src="${opsDefImg}" alt="${car.car_type}" style="width:100%;height:100%;object-fit:contain;" /></div>`
        : `<div class="session-car-thumb no-photo-thumb clickable-thumb" data-id="${car.id}">${car.car_type}</div>`;
    return `
      <div class="ops-row${needsMove ? ' car-needs-move' : ''}">
        ${thumb}
        <div class="session-car-info">
          <span class="session-car-marks">${car.reporting_marks || "—"} ${car.car_number || ""} <span class="muted">${car.car_type}</span></span>
          <span class="session-car-move">${needsMove ? `➡️ ${car.current_location_name || "Unassigned"} → ${dest}` : `📍 ${car.current_location_name || "Unassigned"}`}</span>
        </div>
        ${wb?.industry_name ? `<span class="industry-tag">${wb.industry_name}</span>` : ''}
      </div>
    `;
  }).join("");
}

// ── Operating Session ─────────────────────────────────────────────────────────
let session = null;
// session = { cars: [{id, marks, carType, fromLocation, toLocation, status}], warnings: [] }
// status: 'pending' | 'done' | 'cp'

function saveSession() {
  localStorage.setItem("railcar-session", session ? JSON.stringify(session) : "");
}

function loadSessionFromStorage() {
  try { session = JSON.parse(localStorage.getItem("railcar-session") || "null"); }
  catch { session = null; }
}

function detectSpottingConflicts() {
  if (!session) return;
  const relevant = session.cars.filter(c =>
    (c.group === "arrivals" || c.group === "spots") && c.toIndustryId && c.status !== "cp"
  );
  const byIndustry = {};
  for (const car of relevant) {
    (byIndustry[car.toIndustryId] = byIndustry[car.toIndustryId] || []).push(car);
  }
  const conflicts = [];
  for (const [indId, incoming] of Object.entries(byIndustry)) {
    const ind = industries.find(i => i.id === parseInt(indId));
    const spotNums = (ind?.spot_numbers || "").split(",").filter(s => s.trim());
    if (!spotNums.length) continue;
    const industryCapacity = spotNums.length;
    const currentCount = cars.filter(c =>
      c.current_location_id === ind.location_id &&
      c.active_waybill?.industry_id === ind.id
    ).length;
    if (currentCount + incoming.length > industryCapacity) {
      conflicts.push({ ind, capacity: industryCapacity, spotNums, current: currentCount, cars: incoming });
    }
  }
  session.conflicts = conflicts;
}

function renderSpottingConflicts() {
  const el = document.getElementById("spotting-conflicts");
  if (!el) return;
  const conflicts = session?.conflicts || [];
  if (!conflicts.length) { el.innerHTML = ""; return; }

  el.innerHTML = `
    <div class="conflict-panel">
      <p class="conflict-panel-title">⚠ Spotting Conflicts</p>
      ${conflicts.map(({ ind, capacity, spotNums, current, cars: incoming }) => {
        const available = capacity - current;
        const sorted = [...incoming].sort((a, b) =>
          b.cpSessions - a.cpSessions || a.priority - b.priority
        );
        return `
        <div class="conflict-group" data-ind-id="${ind.id}">
          <div class="conflict-group-header">
            <span><strong>${ind.name}</strong>${spotNums.length ? ` · spots ${spotNums.join(", ")}` : ""} — ${capacity} spot${capacity !== 1 ? "s" : ""}, ${incoming.length} inbound</span>
            <button class="outline small conflict-auto-resolve" data-ind-id="${ind.id}">Auto-resolve</button>
          </div>
          ${sorted.map((car, i) => `
            <div class="conflict-car-row${i < available ? " conflict-will-spot" : " conflict-will-cp"}">
              <span class="conflict-car-marks">${car.marks} <span class="muted">${car.carType}</span></span>
              ${car.cpSessions > 0 ? `<span class="aging-badge">Held ${car.cpSessions} session${car.cpSessions !== 1 ? "s" : ""}</span>` : ""}
              <span class="priority-badge">#${car.priority}</span>
              <span class="conflict-disposition muted small">${i < available ? "✓ spot" : "→ CP"}</span>
            </div>
          `).join("")}
        </div>`;
      }).join("")}
    </div>`;

  el.querySelectorAll(".conflict-auto-resolve").forEach(btn => {
    btn.addEventListener("click", () => {
      const indId = parseInt(btn.dataset.indId);
      const conflict = (session.conflicts || []).find(c => c.ind.id === indId);
      if (!conflict) return;
      const available = conflict.capacity - conflict.current;
      const sorted = [...conflict.cars].sort((a, b) =>
        b.cpSessions - a.cpSessions || a.priority - b.priority
      );
      sorted.slice(available).forEach(car => {
        const sc = session.cars.find(c => c.id === car.id);
        if (sc) sc.status = "cp";
      });
      saveSession();
      detectSpottingConflicts();
      renderSpottingConflicts();
      renderActiveSession();
    });
  });
}

function sessionProgress() {
  if (!session) return { total: 0, done: 0, cp: 0, pending: 0 };
  const total   = session.cars.length;
  const done    = session.cars.filter(c => c.status === "done").length;
  const cp      = session.cars.filter(c => c.status === "cp").length;
  const pending = session.cars.filter(c => c.status === "pending").length;
  return { total, done, cp, pending };
}

function markCar(carId, status) {
  const car = session && session.cars.find(c => c.id === carId);
  if (!car) return;
  // toggle: clicking the same status again resets to pending
  car.status = car.status === status ? "pending" : status;
  saveSession();
  detectSpottingConflicts();
  renderSpottingConflicts();
  renderActiveSession();
}

function renderActiveSession() {
  detectSpottingConflicts();
  renderSpottingConflicts();

  const titleParts = [];
  if (session.trainNumber) titleParts.push(`Train #${session.trainNumber}`);
  if (session.trainName) titleParts.push(`"${session.trainName}"`);
  $("#ops-title").textContent = titleParts.length ? titleParts.join(" ") : "Active Session";

  const warnEl = $("#session-warnings");
  if (session.warnings?.length) {
    warnEl.innerHTML = session.warnings.map(w => `<p style="margin:0.2rem 0">⚠ ${w}</p>`).join("");
    show(warnEl);
  } else {
    hide(warnEl);
  }

  const { total, done, cp, pending } = sessionProgress();
  const allWorked = pending === 0;
  const progressLabel = `${done + cp} / ${total} worked${allWorked ? " — ready to end session" : ""}`;

  $("#ops-header-buttons").innerHTML = `
    <span class="session-progress-label muted">${progressLabel}</span>
    <button id="btn-cancel-session" class="outline secondary">✕ Cancel Session</button>
    <button id="btn-end-session" class="contrast">⬛ End Session</button>
  `;
  document.getElementById("btn-end-session").addEventListener("click", handleEndSession);
  document.getElementById("btn-cancel-session").addEventListener("click", async () => {
    const btn = document.getElementById("btn-cancel-session");
    if (!btn.dataset.confirm) {
      btn.dataset.confirm = "1";
      btn.classList.add("btn-confirming");
      const orig = btn.textContent;
      btn.textContent = "Abandon session?";
      setTimeout(() => { delete btn.dataset.confirm; btn.classList.remove("btn-confirming"); btn.textContent = orig; }, 3000);
      return;
    }
    btn.classList.remove("btn-confirming");
    stopClock();
    const cancelledPlanId = session?.planId;
    session = null;
    saveSession();
    if (cancelledPlanId) {
      try { await api("PATCH", `/api/dispatcher/plan/${cancelledPlanId}/status`, { status: "draft" }); } catch {}
    }
    loadOperations();
  });

  const arrivals   = session.cars.filter(c => c.group === "arrivals");
  const departures = session.cars.filter(c => c.group === "departures");
  const spots      = session.cars.filter(c => c.group === "spots");

  function carRow(car) {
    const statusClass = car.status === "done" ? " done" : car.status === "cp" ? " cp" : "";
    const sessionDefImg = defaultCarImage(car.carType);
    const thumb = car.photoPath
      ? `<div class="session-car-thumb clickable-thumb" data-id="${car.id}"><img src="${photoSrc(car.photoPath, car.photoUrl)}" alt="" /></div>`
      : sessionDefImg
        ? `<div class="session-car-thumb clickable-thumb" data-id="${car.id}"><img src="${sessionDefImg}" alt="${car.carType}" style="width:100%;height:100%;object-fit:contain;" /></div>`
        : `<div class="session-car-thumb no-photo-thumb clickable-thumb" data-id="${car.id}">${car.carType}</div>`;
    return `
      <div class="session-car-row${statusClass}" id="session-row-${car.id}">
        ${thumb}
        <div class="session-car-info">
          <span class="session-car-marks">${car.marks} <span class="muted">${car.carType}</span></span>
          <span class="session-car-move">${car.fromLocation !== car.toLocation ? `➡️ ${car.fromLocation || "?"} → ${car.toLocation || "?"}` : `📍 ${car.fromLocation || "?"}`}</span>
        </div>
        ${car.industryName ? `<span class="industry-tag">${car.industryName}</span>` : ''}
        <div class="session-btn-row">
          <button class="outline small session-done-btn${car.status === "done" ? " active-btn" : ""}" data-id="${car.id}">✓ Done</button>
          <button class="outline small session-cp-btn${car.status === "cp" ? " active-btn" : ""}" data-id="${car.id}">✗ CP</button>
        </div>
      </div>`;
  }

  // Power strip (non-interactive)
  const powerHtml = renderPowerStrip(session.power, session.caboose);

  const noWork = !arrivals.length && !departures.length && !spots.length;
  let html = powerHtml;
  if (noWork) {
    html += `<p class="muted" style="text-align:center;padding:1.5rem">No cars to work this session.</p>`;
  } else {
    if (arrivals.length) {
      html += `<p class="session-section-title">Set out from staging (${arrivals.length})</p>`;
      html += arrivals.map(carRow).join("");
    }
    if (spots.length) {
      html += `<p class="session-section-title">Cars to spot (${spots.length})</p>`;
      html += spots.map(carRow).join("");
    }
    if (departures.length) {
      html += `<p class="session-section-title">Pick up for staging (${departures.length})</p>`;
      html += departures.map(carRow).join("");
    }
  }
  $("#ops-list").innerHTML = html;

  $$(".session-done-btn").forEach(btn => {
    btn.addEventListener("click", () => markCar(parseInt(btn.dataset.id), "done"));
  });
  $$(".session-cp-btn").forEach(btn => {
    btn.addEventListener("click", () => markCar(parseInt(btn.dataset.id), "cp"));
  });
}

async function handleEndSession() {
  const cpCars = session.cars.filter(c => c.status === "cp");
  const doneCars = session.cars.filter(c => c.status === "done");

  if (!doneCars.length && !cpCars.length) {
    showToast("No cars have been marked — work some cars first.", "warn");
    return;
  }

  if (cpCars.length) {
    // Show CP resolution dialog
    const locOptions = locations.map(l => `<option value="${l.id}">${l.name} (${l.location_type})</option>`).join("");
    $("#cp-car-list").innerHTML = cpCars.map(car => `
      <div class="cp-car-row">
        <span class="cp-car-label">${car.marks} <span class="muted">${car.carType}</span></span>
        <select class="cp-location-select" data-id="${car.id}">
          <option value="">— pick location —</option>
          ${locOptions}
        </select>
      </div>
    `).join("");
    $("#end-session-dialog").showModal();
  } else {
    await commitEndSession([]);
  }
}

async function commitEndSession(cpCars) {
  const payload = [
    ...session.cars.filter(c => c.status === "done").map(c => ({ car_id: c.id, status: "done" })),
    ...cpCars,
  ];
  const btn = $("#btn-confirm-end-session");
  try {
    await withLoading(btn || document.body, "Finishing…", async () => {
      const result = await api("POST", "/api/session/end", { cars: payload });
      stopClock();
      if (session?.planId) {
        try { await api("PATCH", `/api/dispatcher/plan/${session.planId}/status`, { status: "complete" }); } catch {}
      }
      session = null;
      saveSession();
      result.updated.forEach(updated => {
        const idx = cars.findIndex(c => c.id === updated.id);
        if (idx !== -1) cars[idx] = updated;
      });
      renderCarGrid();
      if (btn) $("#end-session-dialog").close();
      showToast(`Session complete — ${result.updated.length} car(s) updated.`, "success");
      loadOperations();
    });
  } catch (err) {
    showToast("Error ending session: " + err.message, "error");
  }
}

$("#close-end-session-dialog").addEventListener("click", () => $("#end-session-dialog").close());
$("#btn-cancel-end-session").addEventListener("click", () => $("#end-session-dialog").close());

$("#btn-confirm-end-session").addEventListener("click", async () => {
  const cpSelects = $$(".cp-location-select");
  const cpCars = [];
  for (const sel of cpSelects) {
    if (!sel.value) {
      showToast("Please select a location for every CP car.", "warn");
      return;
    }
    cpCars.push({ car_id: parseInt(sel.dataset.id), status: "cp", location_id: parseInt(sel.value) });
  }
  await commitEndSession(cpCars);
});

// ── Layout setup ──────────────────────────────────────────────────────────────
async function loadLayout() {
  [[locations, industries, commodityMap, carTypes, switchingAreas], settings] = await Promise.all([
    Promise.all([
      api("GET", "/api/locations"),
      api("GET", "/api/industries"),
      api("GET", "/api/commodity-car-type-map"),
      api("GET", "/api/car-types"),
      api("GET", "/api/switching-areas"),
    ]),
    api("GET", "/api/settings"),
  ]);
  renderLocationList();
  renderIndustryList();
  populateIndustryLocationSelect();
  renderCommodityMapList();
  populateCarTypeSelects();
  renderCarTypeList();
  renderSwitchingAreaList();
  populateSwitchingAreaSelect();
  if (settings) {
    $("#clock-start-time").value = settings.clock_start_time;
    $("#clock-speed").value = String(settings.clock_speed);
    opsMode = settings.ops_mode || "free";
    $("#setting-ops-mode").value = opsMode;
  }
}

function populateCarTypeSelect(sel, includeAny) {
  const prev = sel.value;
  const names = carTypes.map(ct => ct.name);
  sel.innerHTML = (includeAny ? '<option value="">— any —</option>' : "") +
    names.map(n => `<option value="${n}">${n}</option>`).join("");
  if (names.includes(prev)) sel.value = prev;
}

function populateCarTypeSelects() {
  populateCarTypeSelect($("#field-type"), false);
  populateCarTypeSelect($("#edit-field-type"), false);
  populateCarTypeSelect($("#we-car-type"), true);
  populateCarTypeSelect($("#cmap-car-type"), false);
}

function updateDefaultImageOffer() {
  if (addMode !== "manual" || photoPath) {
    hide($("#default-image-offer"));
    return;
  }
  const typeName = $("#field-type").value;
  const ct = carTypes.find(t => t.name === typeName);
  if (ct?.default_photo_path) {
    $("#default-offer-thumb").src = `/${ct.default_photo_path}`;
    $("#default-offer-label").textContent = `A default image is available for "${typeName}".`;
    show($("#default-image-offer"));
  } else {
    hide($("#default-image-offer"));
  }
}

$("#field-type").addEventListener("change", updateDefaultImageOffer);

$("#btn-use-default-image").addEventListener("click", () => {
  const typeName = $("#field-type").value;
  const ct = carTypes.find(t => t.name === typeName);
  if (!ct?.default_photo_path) return;
  photoPath = ct.default_photo_path;
  $("#preview-img").src = `/${photoPath}`;
  show($("#upload-preview"));
  hide($("#upload-zone"));
  hide($("#default-image-offer"));
});

$("#btn-dismiss-default-offer").addEventListener("click", () => {
  hide($("#default-image-offer"));
});

function renderCarTypeList() {
  const list = $("#car-type-list");
  if (!carTypes.length) {
    list.innerHTML = '<p class="muted small">No car types defined.</p>';
    return;
  }
  list.innerHTML = carTypes.map(ct => {
    const thumb = ct.default_photo_path
      ? `<img src="/${ct.default_photo_path}" class="car-type-thumb" />`
      : `<div class="car-type-thumb no-photo" style="font-size:0.55rem;">none</div>`;
    return `
    <div class="layout-item">
      ${thumb}
      <span style="flex:1">${ct.name}</span>
      <button class="outline small set-car-type-img" data-id="${ct.id}">Set image</button>
      ${ct.default_photo_path ? `<button class="outline small secondary clear-car-type-img" data-id="${ct.id}">Clear</button>` : ""}
      <button class="outline small contrast del-car-type" data-id="${ct.id}" data-name="${ct.name}">🗑</button>
    </div>`;
  }).join("");
  list.querySelectorAll(".set-car-type-img").forEach(btn => {
    btn.addEventListener("click", () => {
      const id = parseInt(btn.dataset.id);
      openPhotoLibrary(async ({ path }) => {
        await api("PUT", `/api/car-types/${id}/default-image`, { photo_path: path });
        await loadLayout();
      });
    });
  });
  list.querySelectorAll(".clear-car-type-img").forEach(btn => {
    btn.addEventListener("click", async () => {
      await api("PUT", `/api/car-types/${btn.dataset.id}/default-image`, { photo_path: null });
      await loadLayout();
    });
  });
  list.querySelectorAll(".del-car-type").forEach(btn => {
    btn.addEventListener("click", async () => {
      if (!btn.dataset.confirm) {
        btn.dataset.confirm = "1";
        btn.textContent = "Confirm?";
        setTimeout(() => { btn.dataset.confirm = ""; btn.textContent = "🗑"; }, 3000);
        return;
      }
      try {
        await api("DELETE", `/api/car-types/${btn.dataset.id}`);
        await loadLayout();
      } catch (err) {
        showToast(err.message, "error");
      }
    });
  });
}

$("#btn-add-car-type").addEventListener("click", () => {
  $("#car-type-name").value = "";
  show($("#car-type-body"));
  $("#btn-toggle-car-type").textContent = "▼";
  show($("#car-type-form"));
});
$("#btn-cancel-car-type").addEventListener("click", () => hide($("#car-type-form")));
$("#car-type-form").addEventListener("submit", async e => {
  e.preventDefault();
  try {
    await api("POST", "/api/car-types", { name: $("#car-type-name").value.trim() });
    hide($("#car-type-form"));
    await loadLayout();
  } catch (err) {
    showToast("Error: " + err.message, "error");
  }
});

$("#clock-settings-form").addEventListener("submit", async e => {
  e.preventDefault();
  settings = await api("PUT", "/api/settings", {
    clock_start_time: $("#clock-start-time").value,
    clock_speed: parseInt($("#clock-speed").value),
    ops_mode: settings?.ops_mode || "free",
  });
  showToast("Clock settings saved.", "success");
});

$("#ops-mode-form").addEventListener("submit", async e => {
  e.preventDefault();
  const newMode = $("#setting-ops-mode").value;
  settings = await api("PUT", "/api/settings", {
    clock_start_time: settings?.clock_start_time || "08:00",
    clock_speed: settings?.clock_speed || 4,
    ops_mode: newMode,
  });
  opsMode = newMode;
  showToast("Operations mode saved.", "success");
});

function renderLocationList() {
  const list = $("#location-list");
  if (!locations.length) {
    list.innerHTML = emptyState("📍", "No locations yet — add one with the + button.");
    return;
  }
  list.innerHTML = locations.map(l => `
    <div class="layout-item">
      <span><strong>${l.name}</strong> <em>${l.location_type}</em></span>
      <span>
        <button class="outline small edit-loc" data-id="${l.id}">✏️</button>
        <button class="outline small contrast del-loc" data-id="${l.id}">🗑</button>
      </span>
    </div>
  `).join("");

  $$(".edit-loc").forEach(btn => {
    btn.addEventListener("click", () => {
      const loc = locations.find(l => l.id === parseInt(btn.dataset.id));
      if (!loc) return;
      $("#loc-name").value = loc.name;
      $("#loc-type").value = loc.location_type;
      $("#loc-switching-area").value = loc.switching_area_id || "";
      $("#loc-capacity").value = loc.car_capacity ?? "";
      $("#loc-edit-id").value = loc.id;
      show($("#location-form"));
    });
  });

  $$(".del-loc").forEach(btn => {
    btn.addEventListener("click", () => {
      const locId = parseInt(btn.dataset.id);
      const loc = locations.find(l => l.id === locId);
      if (!loc) return;
      if (loc.location_type === "staging") {
        openStagingMergeDialog(loc);
      } else {
        const blocking = cars.filter(c => c.current_location_id === locId);
        if (blocking.length) {
          openLocationBlockDialog(loc, blocking);
        } else {
          confirmThenDeleteLocation(btn, locId);
        }
      }
    });
  });
}

function confirmThenDeleteLocation(btn, locId) {
  if (!btn.dataset.confirm) {
    btn.dataset.confirm = "1";
    btn.classList.add("btn-confirming");
    const orig = btn.innerHTML;
    btn.textContent = "Sure?";
    setTimeout(() => { delete btn.dataset.confirm; btn.classList.remove("btn-confirming"); btn.innerHTML = orig; }, 3000);
    return;
  }
  btn.classList.remove("btn-confirming");
  delete btn.dataset.confirm;
  api("DELETE", `/api/locations/${locId}`)
    .then(() => loadLayout())
    .catch(err => showToast("Error: " + err.message, "error"));
}

function openStagingMergeDialog(loc) {
  const otherStaging = locations.filter(l => l.location_type === "staging" && l.id !== loc.id);
  if (!otherStaging.length) {
    showToast("No other staging locations to merge into — add one first.", "warning");
    return;
  }
  stagingMergeDeleteId = loc.id;
  $("#staging-merge-desc").textContent =
    `"${loc.name}" is a staging location. All cars and waybills will be redirected to the selected location before deletion.`;
  const sel = $("#staging-merge-target");
  sel.innerHTML = otherStaging.map(l => `<option value="${l.id}">${l.name}</option>`).join("");
  $("#staging-merge-dialog").showModal();
}

function openLocationBlockDialog(loc, blockingCars) {
  $("#location-block-desc").textContent =
    `Move the following cars away from "${loc.name}" before deleting it:`;
  $("#location-block-car-list").innerHTML = blockingCars.map(c =>
    `<div class="layout-item">
       <span><strong>${c.reporting_marks || "—"} ${c.car_number || ""}</strong> — ${c.car_type}</span>
     </div>`
  ).join("");
  $("#location-block-dialog").showModal();
}

$("#btn-staging-merge-confirm").addEventListener("click", async () => {
  const mergeInto = parseInt($("#staging-merge-target").value);
  if (!stagingMergeDeleteId || isNaN(mergeInto)) return;
  try {
    await api("DELETE", `/api/locations/${stagingMergeDeleteId}?merge_into_id=${mergeInto}`);
    $("#staging-merge-dialog").close();
    showToast("Staging location merged and deleted.", "success");
    await loadLayout();
    cars = await api("GET", "/api/cars");
    renderCarGrid();
  } catch (err) {
    showToast("Error: " + err.message, "error");
  }
});
["#btn-staging-merge-cancel", "#btn-close-staging-merge"].forEach(sel =>
  $(sel).addEventListener("click", () => {
    stagingMergeDeleteId = null;
    $("#staging-merge-dialog").close();
  })
);

["#btn-location-block-close", "#btn-close-location-block"].forEach(sel =>
  $(sel).addEventListener("click", () => $("#location-block-dialog").close())
);

function checkboxesToRole() {
  const recv = $("#ind-receiver").checked;
  const ship = $("#ind-shipper").checked;
  if (recv && ship) return "transload";
  if (ship)         return "producer";
  return "consumer";
}

function syncDirectionSections() {
  if ($("#ind-receiver").checked) show($("#ind-inbound-section"));
  else hide($("#ind-inbound-section"));
  if ($("#ind-shipper").checked) show($("#ind-outbound-section"));
  else hide($("#ind-outbound-section"));
}

function roleToCheckboxes(role) {
  $("#ind-receiver").checked = (role !== "producer");
  $("#ind-shipper").checked  = (role === "producer" || role === "transload");
  syncDirectionSections();
}

$("#ind-receiver").addEventListener("change", syncDirectionSections);
$("#ind-shipper").addEventListener("change", syncDirectionSections);

function renderIndustryList() {
  const list = $("#industry-list");
  if (!industries.length) {
    list.innerHTML = emptyState("🏭", "No industries yet — add one with the + button.");
    return;
  }
  const roleBadge = r => r === "producer" ? "producer" : r === "transload" ? "transload" : "";

  function unmappedChipsHtml(commodityCsv, direction, indId) {
    const tokens = (commodityCsv || "").split(",").map(t => t.trim().toLowerCase()).filter(Boolean);
    const unmapped = tokens.filter(t => !commodityMap.find(m => m.commodity === t));
    if (!unmapped.length) return "";
    return `<div class="ind-unmapped-row">
      <span class="ind-unmapped-label">⚠ unmapped (${direction}):</span>
      ${unmapped.map(c =>
        `<span class="chip-group">` +
        `<button type="button" class="outline small cmap-add-chip" data-commodity="${c}" data-ind-id="${indId}" data-field="${direction}">+ ${c}</button>` +
        `<button type="button" class="outline small contrast cmap-dismiss-chip" data-commodity="${c}" data-ind-id="${indId}" data-field="${direction}" title="Remove from industry">×</button>` +
        `</span>`
      ).join("")}
    </div>`;
  }

  list.innerHTML = industries.map(i => {
    const allCommodities = [i.commodities, i.outbound_commodities].filter(Boolean).join(", ");
    return `
      <div class="layout-item layout-item-stack">
        <div class="layout-item-main">
          <span>
            <strong>${i.name}</strong>
            ${i.location_name ? `<em>@ ${i.location_name}</em>` : ""}
            ${roleBadge(i.industry_role) ? `<span class='waybill-badge muted'>${roleBadge(i.industry_role)}</span>` : ""}
            ${allCommodities ? `<span class='muted'>${allCommodities}</span>` : ""}
          </span>
          <span>
            <button class="outline small edit-ind" data-id="${i.id}">✏️</button>
            <button class="outline small contrast del-ind" data-id="${i.id}">🗑</button>
          </span>
        </div>
        ${unmappedChipsHtml(i.commodities, "inbound", i.id)}
        ${unmappedChipsHtml(i.outbound_commodities, "outbound", i.id)}
      </div>`;
  }).join("");

  $$(".edit-ind").forEach(btn => {
    btn.addEventListener("click", () => {
      const ind = industries.find(i => i.id === parseInt(btn.dataset.id));
      if (!ind) return;
      $("#ind-name").value = ind.name;
      $("#ind-location").value = ind.location_id || "";
      refreshSpotPickerForLocation(ind.spot_numbers || "");
      populateCarTypeMultiSelect($("#ind-inbound-car-types"), ind.inbound_car_types || ind.accepted_car_types || "");
      $("#ind-inbound-commodities").value = ind.commodities || "";
      populateCarTypeMultiSelect($("#ind-outbound-car-types"), ind.outbound_car_types || "");
      $("#ind-outbound-commodities").value = ind.outbound_commodities || "";
      $("#ind-edit-id").value = ind.id;
      roleToCheckboxes(ind.industry_role || "consumer");
      hide($("#inbound-commodity-warn"));
      hide($("#outbound-commodity-warn"));
      show($("#industry-form"));
    });
  });

  $$(".del-ind").forEach(btn => {
    btn.addEventListener("click", async () => {
      if (!btn.dataset.confirm) {
        btn.dataset.confirm = "1";
        btn.classList.add("btn-confirming");
        const orig = btn.innerHTML;
        btn.textContent = "Sure?";
        setTimeout(() => { delete btn.dataset.confirm; btn.classList.remove("btn-confirming"); btn.innerHTML = orig; }, 3000);
        return;
      }
      btn.classList.remove("btn-confirming");
      delete btn.dataset.confirm;
      try {
        await api("DELETE", `/api/industries/${btn.dataset.id}`);
        await loadLayout();
      } catch (err) {
        showToast("Error: " + err.message, "error");
      }
    });
  });

  // Inline unmapped chip handlers
  list.addEventListener("click", async e => {
    const indId = parseInt(e.target.closest("[data-ind-id]")?.dataset.indId);
    const ind = industries.find(i => i.id === indId);
    if (!ind) return;

    const dismiss = e.target.closest(".cmap-dismiss-chip");
    if (dismiss) {
      const commodity = dismiss.dataset.commodity;
      const field = dismiss.dataset.field;
      const srcVal = field === "outbound" ? (ind.outbound_commodities || "") : (ind.commodities || "");
      const updated = srcVal.split(",").map(t => t.trim()).filter(t => t.toLowerCase() !== commodity.toLowerCase()).join(", ");
      const patch = {
        name: ind.name,
        location_id: ind.location_id || null,
        accepted_car_types: ind.accepted_car_types || "",
        commodities: field === "outbound" ? (ind.commodities || "") : updated,
        industry_role: ind.industry_role || "consumer",
        inbound_car_types: ind.inbound_car_types || "",
        outbound_commodities: field === "outbound" ? updated : (ind.outbound_commodities || ""),
        outbound_car_types: ind.outbound_car_types || "",
      };
      await api("PUT", `/api/industries/${indId}`, patch);
      await loadLayout();
      return;
    }

    const chip = e.target.closest(".cmap-add-chip");
    if (chip) {
      const commodity = chip.dataset.commodity;
      const body = $("#commodity-map-body");
      if (body.classList.contains("hidden")) {
        body.classList.remove("hidden");
        $("#btn-toggle-commodity-map").textContent = "▼";
      }
      show($("#commodity-map-form"));
      $("#cmap-edit-id").value = "";
      $("#cmap-commodity").value = commodity;
      body.scrollIntoView({ behavior: "smooth", block: "nearest" });
      $("#btn-suggest-cmap").click();
    }
  });
}

function populateCarTypeMultiSelect(el, selectedStr) {
  const selected = new Set((selectedStr || "").split(",").map(s => s.trim().toLowerCase()).filter(Boolean));
  if (!carTypes.length) {
    el.innerHTML = '<span class="muted" style="font-size:0.8rem">No car types defined</span>';
    return;
  }
  el.innerHTML = carTypes.map(ct => {
    const checked = selected.has(ct.name.toLowerCase()) ? " checked" : "";
    const id = `ct-pick-${el.id}-${ct.name.replace(/\s+/g, "-")}`;
    return `<label class="ct-pill"><input type="checkbox" value="${ct.name}"${checked} id="${id}"><span>${ct.name}</span></label>`;
  }).join("");
}

function getMultiSelectValues(el) {
  return Array.from(el.querySelectorAll('input[type="checkbox"]:checked')).map(cb => cb.value).join(", ");
}

function populateSpotPicker(el, capacity, selectedStr) {
  const selected = new Set((selectedStr || "").split(",").map(s => s.trim()).filter(Boolean));
  const total = capacity || 0;
  if (!total) {
    el.innerHTML = '<span class="muted" style="font-size:0.8rem">Select a location to see spots</span>';
    return;
  }
  el.innerHTML = Array.from({ length: total }, (_, i) => {
    const n = String(i + 1);
    const checked = selected.has(n) ? " checked" : "";
    return `<label class="ct-pill"><input type="checkbox" value="${n}"${checked}><span>${n}</span></label>`;
  }).join("");
}

function getSpotPickerValues(el) {
  return Array.from(el.querySelectorAll('input[type="checkbox"]:checked')).map(cb => cb.value).join(", ");
}

function populateIndustryLocationSelect() {
  const sel = $("#ind-location");
  sel.innerHTML = '<option value="">— no location —</option>' +
    locations.map(l => `<option value="${l.id}">${l.name}</option>`).join("");
}

function refreshSpotPickerForLocation(selectedStr = "") {
  const locId = parseInt($("#ind-location").value);
  const loc = locations.find(l => l.id === locId);
  populateSpotPicker($("#ind-spot-numbers"), loc?.car_capacity ?? 0, selectedStr);
}

$("#ind-location").addEventListener("change", () => refreshSpotPickerForLocation());

$("#btn-add-location").addEventListener("click", () => {
  $("#loc-name").value = "";
  $("#loc-type").value = "yard";
  $("#loc-switching-area").value = "";
  $("#loc-capacity").value = "";
  $("#loc-edit-id").value = "";
  show($("#location-form"));
});
$("#btn-cancel-location").addEventListener("click", () => hide($("#location-form")));

$("#location-form").addEventListener("submit", async e => {
  e.preventDefault();
  const editId = $("#loc-edit-id").value;
  const saVal = $("#loc-switching-area").value;
  const body = {
    name: $("#loc-name").value.trim(),
    location_type: $("#loc-type").value,
    switching_area_id: saVal ? parseInt(saVal) : null,
    car_capacity: $("#loc-capacity").value ? parseInt($("#loc-capacity").value) : null,
  };
  if (editId) {
    await api("PUT", `/api/locations/${editId}`, body);
  } else {
    await api("POST", "/api/locations", body);
  }
  hide($("#location-form"));
  await loadLayout();
});

$("#btn-add-industry").addEventListener("click", () => {
  $("#ind-name").value = "";
  $("#ind-location").value = "";
  populateCarTypeMultiSelect($("#ind-inbound-car-types"), "");
  $("#ind-inbound-commodities").value = "";
  populateCarTypeMultiSelect($("#ind-outbound-car-types"), "");
  $("#ind-outbound-commodities").value = "";
  populateSpotPicker($("#ind-spot-numbers"), 0, "");
  $("#ind-edit-id").value = "";
  roleToCheckboxes("consumer");
  hide($("#inbound-commodity-warn"));
  hide($("#outbound-commodity-warn"));
  show($("#industry-form"));
});
$("#btn-cancel-industry").addEventListener("click", () => hide($("#industry-form")));

$("#btn-suggest-industry").addEventListener("click", async () => {
  const description = $("#ind-name").value.trim();
  if (!description) { showToast("Enter an industry name first", "warning"); return; }
  const btn = $("#btn-suggest-industry");
  const original = btn.textContent;
  btn.textContent = "⏳ Thinking…";
  btn.disabled = true;
  try {
    const result = await api("POST", "/api/industries/suggest", { description });
    if (result.industry_role) roleToCheckboxes(result.industry_role);
    if (result.inbound_commodities)  $("#ind-inbound-commodities").value  = result.inbound_commodities;
    if (result.inbound_car_types)    populateCarTypeMultiSelect($("#ind-inbound-car-types"), result.inbound_car_types);
    if (result.outbound_commodities) $("#ind-outbound-commodities").value = result.outbound_commodities;
    if (result.outbound_car_types)   populateCarTypeMultiSelect($("#ind-outbound-car-types"), result.outbound_car_types);
  } catch (err) {
    showToast("AI suggestion failed — check ANTHROPIC_API_KEY", "error");
  } finally {
    btn.textContent = original;
    btn.disabled = false;
  }
});

$("#industry-form").addEventListener("submit", async e => {
  e.preventDefault();
  const editId = $("#ind-edit-id").value;
  const locVal = $("#ind-location").value;
  if (!locVal) {
    showToast("A location is required before saving an industry.", "error");
    $("#ind-location").focus();
    return;
  }
  const body = {
    name: $("#ind-name").value.trim(),
    location_id: parseInt(locVal),
    accepted_car_types: "",
    commodities: $("#ind-inbound-commodities").value.trim(),
    industry_role: checkboxesToRole(),
    inbound_car_types: getMultiSelectValues($("#ind-inbound-car-types")),
    outbound_commodities: $("#ind-outbound-commodities").value.trim(),
    outbound_car_types: getMultiSelectValues($("#ind-outbound-car-types")),
    spot_numbers: getSpotPickerValues($("#ind-spot-numbers")),
  };
  if (editId) {
    await api("PUT", `/api/industries/${editId}`, body);
  } else {
    await api("POST", "/api/industries", body);
  }
  hide($("#industry-form"));
  await loadLayout();
});

// ── Commodity autocomplete ────────────────────────────────────────────────────

function refreshCommodityWarning(inputEl, warnEl) {
  const tokens = inputEl.value.split(",").map(t => t.trim().toLowerCase()).filter(Boolean);
  const unknown = tokens.filter(t => !commodityMap.find(m => m.commodity === t));
  if (!unknown.length) { hide(warnEl); return; }
  warnEl.innerHTML = "⚠ Not in commodity map: " +
    unknown.map(c =>
      `<span class="chip-group">` +
      `<button type="button" class="outline small cmap-add-chip" data-commodity="${c}">+ ${c}</button>` +
      `<button type="button" class="outline small contrast cmap-dismiss-chip" data-commodity="${c}" title="Remove from industry">×</button>` +
      `</span>`
    ).join(" ");
  show(warnEl);
}

function refreshAllCommodityWarnings() {
  refreshCommodityWarning($("#ind-inbound-commodities"), $("#inbound-commodity-warn"));
  refreshCommodityWarning($("#ind-outbound-commodities"), $("#outbound-commodity-warn"));
}

function setupCommodityAutocomplete(inputId, dropdownId, warnId) {
  const input    = $(inputId);
  const dropdown = $(dropdownId);
  const warnEl   = $(warnId);

  function currentToken() {
    const val = input.value;
    return val.slice(val.lastIndexOf(",") + 1).trim().toLowerCase();
  }

  function completeToken(commodity) {
    const val = input.value;
    const idx = val.lastIndexOf(",");
    const prefix = idx >= 0 ? val.slice(0, idx + 1) + " " : "";
    input.value = prefix + commodity + ", ";
    dropdown.classList.add("hidden");
    input.focus();
  }

  input.addEventListener("input", () => {
    const token = currentToken();
    hide(warnEl);
    if (!token || !commodityMap.length) { hide(dropdown); return; }
    const matches = commodityMap.filter(m => m.commodity.includes(token));
    if (!matches.length) { hide(dropdown); return; }
    dropdown.innerHTML = matches.map(m =>
      `<li class="suggestion-item" data-commodity="${m.commodity}">
        <span>${m.commodity}</span>
        <span class="suggestion-car-type">${m.car_type}</span>
      </li>`
    ).join("");
    dropdown.querySelectorAll(".suggestion-item").forEach(li =>
      li.addEventListener("mousedown", e => { e.preventDefault(); completeToken(li.dataset.commodity); })
    );
    show(dropdown);
  });

  input.addEventListener("blur", () => {
    hide(dropdown);
    refreshCommodityWarning(input, warnEl);
  });

  warnEl.addEventListener("click", async e => {
    const dismiss = e.target.closest(".cmap-dismiss-chip");
    if (dismiss) {
      const commodity = dismiss.dataset.commodity;
      const current = input.value.split(",").map(t => t.trim()).filter(Boolean);
      input.value = current.filter(t => t.toLowerCase() !== commodity.toLowerCase()).join(", ");
      const editId = $("#ind-edit-id").value;
      if (editId) {
        await api("PUT", `/api/industries/${editId}`, {
          name: $("#ind-name").value.trim(),
          location_id: $("#ind-location").value ? parseInt($("#ind-location").value) : null,
          accepted_car_types: "",
          commodities: $("#ind-inbound-commodities").value.trim(),
          industry_role: checkboxesToRole(),
          inbound_car_types: getMultiSelectValues($("#ind-inbound-car-types")),
          outbound_commodities: $("#ind-outbound-commodities").value.trim(),
          outbound_car_types: getMultiSelectValues($("#ind-outbound-car-types")),
        });
        await loadLayout();
      }
      refreshCommodityWarning(input, warnEl);
      return;
    }

    const chip = e.target.closest(".cmap-add-chip");
    if (!chip) return;
    const commodity = chip.dataset.commodity;
    const body = $("#commodity-map-body");
    if (body.classList.contains("hidden")) {
      body.classList.remove("hidden");
      $("#btn-toggle-commodity-map").textContent = "▼";
    }
    show($("#commodity-map-form"));
    $("#cmap-edit-id").value = "";
    $("#cmap-commodity").value = commodity;
    body.scrollIntoView({ behavior: "smooth", block: "nearest" });
    $("#btn-suggest-cmap").click();
  });
}

setupCommodityAutocomplete("#ind-inbound-commodities",  "#inbound-commodity-suggestions",  "#inbound-commodity-warn");
setupCommodityAutocomplete("#ind-outbound-commodities", "#outbound-commodity-suggestions", "#outbound-commodity-warn");

// ── Commodity → Car Type map ──────────────────────────────────────────────────
function renderCommodityMapList() {
  const list = $("#commodity-map-list");
  if (!commodityMap.length) {
    list.innerHTML = emptyState("🗂", "No mappings yet — click ⚙ Seed Defaults to populate common commodities.");
    return;
  }
  list.innerHTML = commodityMap.map(m => `
    <div class="layout-item">
      <span><strong>${m.commodity}</strong> <em>→ ${m.car_type}</em></span>
      <span>
        <button class="outline small edit-cmap" data-id="${m.id}">✏️</button>
        <button class="outline small contrast del-cmap" data-id="${m.id}">🗑</button>
      </span>
    </div>
  `).join("");

  $$(".edit-cmap").forEach(btn => {
    btn.addEventListener("click", () => {
      const entry = commodityMap.find(m => m.id === parseInt(btn.dataset.id));
      if (!entry) return;
      $("#cmap-commodity").value = entry.commodity;
      $("#cmap-car-type").value = entry.car_type;
      $("#cmap-edit-id").value = entry.id;
      $("#cmap-commodity").disabled = true;
      show($("#commodity-map-form"));
    });
  });

  $$(".del-cmap").forEach(btn => {
    btn.addEventListener("click", async () => {
      if (!btn.dataset.confirm) {
        btn.dataset.confirm = "1";
        btn.classList.add("btn-confirming");
        const orig = btn.innerHTML;
        btn.textContent = "Sure?";
        setTimeout(() => { delete btn.dataset.confirm; btn.classList.remove("btn-confirming"); btn.innerHTML = orig; }, 3000);
        return;
      }
      btn.classList.remove("btn-confirming");
      delete btn.dataset.confirm;
      try {
        await api("DELETE", `/api/commodity-car-type-map/${btn.dataset.id}`);
        await loadLayout();
      } catch (err) {
        showToast("Error: " + err.message, "error");
      }
    });
  });
}

$("#btn-toggle-commodity-map").addEventListener("click", () => {
  const body = $("#commodity-map-body");
  const btn  = $("#btn-toggle-commodity-map");
  const collapsed = body.classList.toggle("hidden");
  btn.textContent = collapsed ? "▶" : "▼";
});

$("#btn-toggle-car-type").addEventListener("click", () => {
  const body = $("#car-type-body");
  const btn  = $("#btn-toggle-car-type");
  const collapsed = body.classList.toggle("hidden");
  btn.textContent = collapsed ? "▶" : "▼";
});

$("#btn-add-commodity-map").addEventListener("click", () => {
  $("#cmap-commodity").value = "";
  $("#cmap-car-type").value = "boxcar";
  $("#cmap-edit-id").value = "";
  $("#cmap-commodity").disabled = false;
  show($("#commodity-map-form"));
});

$("#btn-cancel-commodity-map").addEventListener("click", () => {
  hide($("#commodity-map-form"));
  $("#cmap-commodity").disabled = false;
});

$("#btn-suggest-cmap").addEventListener("click", async () => {
  const commodity = $("#cmap-commodity").value.trim();
  if (!commodity) { showToast("Enter a commodity name first", "warning"); return; }
  const btn = $("#btn-suggest-cmap");
  const original = btn.textContent;
  btn.textContent = "⏳";
  btn.disabled = true;
  try {
    const result = await api("POST", "/api/commodity-car-type-map/suggest", { commodity });
    if (result.car_type) $("#cmap-car-type").value = result.car_type;
  } catch (err) {
    showToast("AI suggestion failed — check your AI provider settings", "error");
  } finally {
    btn.textContent = original;
    btn.disabled = false;
  }
});

$("#commodity-map-form").addEventListener("submit", async e => {
  e.preventDefault();
  const editId = $("#cmap-edit-id").value;
  try {
    if (editId) {
      await api("PUT", `/api/commodity-car-type-map/${editId}`, {
        car_type: $("#cmap-car-type").value,
      });
    } else {
      await api("POST", "/api/commodity-car-type-map", {
        commodity: $("#cmap-commodity").value.trim(),
        car_type: $("#cmap-car-type").value,
      });
    }
    hide($("#commodity-map-form"));
    $("#cmap-commodity").disabled = false;
    await loadLayout();
    refreshAllCommodityWarnings();
  } catch (err) {
    showToast("Error saving mapping: " + err.message, "error");
  }
});

$("#btn-seed-commodity-map").addEventListener("click", async () => {
  const btn = $("#btn-seed-commodity-map");
  try {
    await withLoading(btn, "Seeding…", async () => {
      const result = await api("POST", "/api/commodity-car-type-map/seed");
      showToast(`Added ${result.added} mapping${result.added !== 1 ? "s" : ""}, skipped ${result.skipped}.`, "success");
      await loadLayout();
    });
  } catch (err) {
    showToast("Error seeding defaults: " + err.message, "error");
  }
});

// ── Export / Import ───────────────────────────────────────────────────────────
$("#btn-open-photo-library").addEventListener("click", () => openPhotoLibrary(null));

$("#btn-export-backup").addEventListener("click", () => {
  const a = document.createElement("a");
  a.href = "/api/export";
  a.download = "";
  a.click();
});

$("#btn-import-trigger").addEventListener("click", () => {
  const btn = $("#btn-import-trigger");
  if (!btn.dataset.confirm) {
    btn.dataset.confirm = "1";
    btn.classList.add("btn-confirming");
    const orig = btn.textContent;
    btn.textContent = "⚠ Replace ALL data? Click again.";
    setTimeout(() => { delete btn.dataset.confirm; btn.classList.remove("btn-confirming"); btn.textContent = orig; }, 5000);
    return;
  }
  btn.classList.remove("btn-confirming");
  delete btn.dataset.confirm;
  btn.textContent = "⬆ Import Backup";
  $("#import-file-input").click();
});

$("#btn-purge-uploads").addEventListener("click", async () => {
  const btn = $("#btn-purge-uploads");
  if (!btn.dataset.confirm) {
    btn.dataset.confirm = "1";
    btn.classList.add("btn-confirming");
    const orig = btn.textContent;
    btn.textContent = "⚠ Delete unassigned? Click again.";
    setTimeout(() => { delete btn.dataset.confirm; btn.classList.remove("btn-confirming"); btn.textContent = orig; }, 4000);
    return;
  }
  btn.classList.remove("btn-confirming");
  delete btn.dataset.confirm;
  try {
    await withLoading(btn, "Purging…", async () => {
      const result = await api("POST", "/api/uploads/purge");
      showToast(`Deleted ${result.deleted} unassigned photo${result.deleted !== 1 ? "s" : ""}.`, "success");
      await refreshLibraryGrid();
    });
  } catch (err) {
    showToast("Purge failed: " + err.message, "error");
  }
});

$("#import-file-input").addEventListener("change", async e => {
  const file = e.target.files[0];
  if (!file) return;
  const btn = $("#btn-import-trigger");
  const fd = new FormData();
  fd.append("file", file);
  try {
    await withLoading(btn, "Importing…", async () => {
      await api("POST", "/api/import", fd);
      location.reload();
    });
  } catch (err) {
    showToast("Import failed: " + err.message, "error");
    e.target.value = "";
  }
});

// ── Import Cars dialog ───────────────────────────────────────────────────────

let importCarsPreviewData = null;

function openImportCarsDialog() {
  importCarsPreviewData = null;
  show($("#import-cars-file-area"));
  hide($("#import-cars-preview"));
  hide($("#btn-import-cars-confirm"));
  hide($("#import-cars-errors"));
  $("#import-cars-table tbody").innerHTML = "";
  $("#import-cars-summary").textContent = "";
  $("input[name='import-cars-mode'][value='add']").checked = true;
  $("#import-cars-dialog").showModal();
}

$("#btn-import-cars").addEventListener("click", openImportCarsDialog);
$("#close-import-cars-dialog").addEventListener("click", () => $("#import-cars-dialog").close());
$("#btn-cancel-import-cars").addEventListener("click", () => $("#import-cars-dialog").close());

$("#btn-import-cars-pick").addEventListener("click", () => $("#import-cars-file").click());

$("#import-cars-file").addEventListener("change", async e => {
  const file = e.target.files[0];
  if (!file) return;
  const btn = $("#btn-import-cars-pick");
  btn.textContent = "⏳ Parsing…";
  btn.disabled = true;
  try {
    const fd = new FormData();
    fd.append("file", file);
    fd.append("mode", "add");
    fd.append("dry_run", "true");
    const token = _authToken();
    const result = await fetch("/api/import/cars", {
      method: "POST", body: fd,
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    }).then(async r => {
      if (!r.ok) throw new Error(await r.text());
      return r.json();
    });
    importCarsPreviewData = result;

    const errEl = $("#import-cars-errors");
    if (result.errors?.length) {
      errEl.textContent = result.errors.join("\n");
      show(errEl);
    } else {
      hide(errEl);
    }

    let summary = `${result.total} car${result.total !== 1 ? "s" : ""} ready to import`;
    if (result.skipped_duplicates) summary += ` (${result.skipped_duplicates} duplicate${result.skipped_duplicates !== 1 ? "s" : ""} will be skipped)`;
    $("#import-cars-summary").textContent = summary;

    const tbody = $("#import-cars-table tbody");
    tbody.innerHTML = (result.preview || []).map(c =>
      `<tr><td>${c.reporting_marks}</td><td>${c.car_number}</td><td>${c.car_type}</td><td>${c.color || "—"}</td></tr>`
    ).join("");
    if (result.total > 8) {
      tbody.innerHTML += `<tr><td colspan="4" class="muted">… and ${result.total - 8} more</td></tr>`;
    }

    show($("#import-cars-preview"));
    hide($("#import-cars-file-area"));
    if (result.total > 0) show($("#btn-import-cars-confirm"));
  } catch (err) {
    showToast("Parse failed: " + err.message, "error");
  } finally {
    btn.textContent = "Choose CSV or JMRI XML file…";
    btn.disabled = false;
    e.target.value = "";
  }
});

$("#btn-import-cars-confirm").addEventListener("click", async () => {
  if (!importCarsPreviewData) return;
  const file = $("#import-cars-file");
  const mode = $("input[name='import-cars-mode']:checked").value;
  const btn = $("#btn-import-cars-confirm");

  if (mode === "replace" && !btn.dataset.confirm) {
    btn.dataset.confirm = "1";
    const orig = btn.textContent;
    btn.textContent = "Replace all? Confirm";
    btn.classList.add("btn-confirming");
    setTimeout(() => { delete btn.dataset.confirm; btn.textContent = orig; btn.classList.remove("btn-confirming"); }, 3000);
    return;
  }
  delete btn.dataset.confirm;
  btn.classList.remove("btn-confirming");

  // Re-send the file with dry_run=false
  try {
    const token = _authToken();
    const headers = { "Content-Type": "application/json" };
    if (token) headers["Authorization"] = `Bearer ${token}`;
    const resp = await fetch("/api/import/cars/commit", {
      method: "POST",
      headers,
      body: JSON.stringify({ cars: importCarsPreviewData.rows, mode }),
    });
    const result = await resp.json();
    $("#import-cars-dialog").close();
    await loadRoster();
    showToast(`Imported ${result.imported} car${result.imported !== 1 ? "s" : ""}`, "success");
  } catch (err) {
    showToast("Import failed: " + err.message, "error");
  }
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

// ── Switching Areas ───────────────────────────────────────────────────────────

function populateSwitchingAreaSelect() {
  const sel = $("#loc-switching-area");
  const prev = sel.value;
  sel.innerHTML = '<option value="">— no switching area —</option>' +
    switchingAreas.map(a => `<option value="${a.id}">${a.name}</option>`).join("");
  if (prev) sel.value = prev;
}

function renderSwitchingAreaList() {
  const list = $("#switching-area-list");
  if (!list) return;
  if (!switchingAreas.length) {
    list.innerHTML = '<p class="muted small">No switching areas defined.</p>';
    return;
  }
  list.innerHTML = switchingAreas.map(a => {
    const locBadges = (a.locations || []).map(l =>
      `<span class="waybill-badge muted">${l.name}</span>`
    ).join(" ");
    const count = a.current_car_count ?? 0;
    const cap = a.car_capacity ?? 10;
    return `
    <div class="layout-item layout-item-stack">
      <div class="layout-item-main">
        <span style="flex:1">
          <strong>${a.name}</strong>
          <span class="muted">${count}/${cap} cars</span>
          ${locBadges}
        </span>
        <span>
          <button class="outline small edit-sa" data-id="${a.id}">✏️</button>
          <button class="outline small contrast del-sa" data-id="${a.id}" data-name="${a.name}">🗑</button>
        </span>
      </div>
    </div>`;
  }).join("");

  list.querySelectorAll(".edit-sa").forEach(btn => {
    btn.addEventListener("click", () => {
      const area = switchingAreas.find(a => a.id === parseInt(btn.dataset.id));
      if (!area) return;
      $("#sa-name").value = area.name;
      $("#sa-capacity").value = area.car_capacity;
      $("#sa-edit-id").value = area.id;
      show($("#switching-area-form"));
    });
  });

  list.querySelectorAll(".del-sa").forEach(btn => {
    btn.addEventListener("click", async () => {
      if (!btn.dataset.confirm) {
        btn.dataset.confirm = "1";
        btn.classList.add("btn-confirming");
        const orig = btn.innerHTML;
        btn.textContent = "Sure?";
        setTimeout(() => { delete btn.dataset.confirm; btn.classList.remove("btn-confirming"); btn.innerHTML = orig; }, 3000);
        return;
      }
      btn.classList.remove("btn-confirming");
      delete btn.dataset.confirm;
      try {
        await api("DELETE", `/api/switching-areas/${btn.dataset.id}`);
        await loadLayout();
      } catch (err) {
        showToast("Error: " + err.message, "error");
      }
    });
  });
}

$("#btn-toggle-switching-areas").addEventListener("click", () => {
  const body = $("#switching-area-body");
  const btn = $("#btn-toggle-switching-areas");
  const collapsed = body.classList.toggle("hidden");
  btn.textContent = collapsed ? "▶" : "▼";
});

$("#btn-add-switching-area").addEventListener("click", () => {
  $("#sa-name").value = "";
  $("#sa-capacity").value = "10";
  $("#sa-edit-id").value = "";
  show($("#switching-area-body"));
  $("#btn-toggle-switching-areas").textContent = "▼";
  show($("#switching-area-form"));
});
$("#btn-cancel-switching-area").addEventListener("click", () => hide($("#switching-area-form")));

$("#switching-area-form").addEventListener("submit", async e => {
  e.preventDefault();
  const editId = $("#sa-edit-id").value;
  const body = {
    name: $("#sa-name").value.trim(),
    car_capacity: parseInt($("#sa-capacity").value),
  };
  try {
    if (editId) {
      await api("PUT", `/api/switching-areas/${editId}`, body);
    } else {
      await api("POST", "/api/switching-areas", body);
    }
    hide($("#switching-area-form"));
    await loadLayout();
  } catch (err) {
    showToast("Error: " + err.message, "error");
  }
});

// ── Layout Status strip ───────────────────────────────────────────────────────

async function renderLayoutStatus() {
  const areasEl = $("#layout-status-areas");
  const yardsEl = $("#layout-status-yards");
  if (!areasEl || !yardsEl) return;
  let status;
  try {
    status = await api("GET", "/api/layout-status");
  } catch {
    return;
  }

  function carListHtml(cars) {
    if (!cars.length) return '<p class="muted small" style="margin:0.25rem 0.5rem">No cars here.</p>';
    return cars.map(c =>
      `<div class="layout-item" style="padding:0.2rem 0.5rem;font-size:0.8rem">
         <span><strong>${c.reporting_marks || "—"} ${c.car_number || ""}</strong> <em>${c.car_type}</em></span>
         <span class="muted">${c.destination_name ? "→ " + c.destination_name : "—"}</span>
       </div>`
    ).join("");
  }

  areasEl.innerHTML = status.switching_areas.map(a => {
    const pct = a.car_capacity > 0 ? Math.round((a.current_car_count / a.car_capacity) * 100) : 0;
    return `
    <div class="layout-status-row">
      <div class="layout-status-summary" data-toggle="sa-${a.id}" style="cursor:pointer;display:flex;align-items:center;gap:0.5rem;padding:0.3rem 0">
        <span style="flex:1"><strong>${a.name}</strong></span>
        <span class="muted" style="font-size:0.8rem">${a.current_car_count}/${a.car_capacity}</span>
        <progress value="${pct}" max="100" style="width:5rem;height:0.6rem"></progress>
        <span class="muted" style="font-size:0.75rem">▶</span>
      </div>
      <div id="sa-detail-${a.id}" class="hidden">${carListHtml(a.cars || [])}</div>
    </div>`;
  }).join("") || '<p class="muted small">No switching areas defined.</p>';

  yardsEl.innerHTML = status.yards.map(y => `
    <div class="layout-status-row">
      <div class="layout-status-summary" data-toggle="yard-${y.id}" style="cursor:pointer;display:flex;align-items:center;gap:0.5rem;padding:0.3rem 0">
        <span style="flex:1"><strong>${y.name}</strong> <em class="muted">${y.location_type}</em></span>
        <span class="muted" style="font-size:0.8rem">${y.car_count} cars</span>
        <span class="muted" style="font-size:0.75rem">▶</span>
      </div>
      <div id="yard-detail-${y.id}" class="hidden">${carListHtml(y.cars || [])}</div>
    </div>`
  ).join("") || '<p class="muted small">No yards or staging areas.</p>';

  document.querySelectorAll(".layout-status-summary").forEach(row => {
    row.addEventListener("click", () => {
      const key = row.dataset.toggle;
      const detail = document.getElementById(`${key.startsWith("sa-") ? "sa-detail-" + key.slice(3) : "yard-detail-" + key.slice(5)}`);
      const arrow = row.querySelector("span:last-child");
      if (detail) {
        const hidden = detail.classList.toggle("hidden");
        if (arrow) arrow.textContent = hidden ? "▶" : "▼";
      }
    });
  });
}

$("#btn-toggle-layout-status").addEventListener("click", () => {
  const body = $("#layout-status-body");
  const btn = $("#btn-toggle-layout-status");
  const collapsed = body.classList.toggle("hidden");
  btn.textContent = collapsed ? "▶" : "▼";
});

// ── Dispatcher ────────────────────────────────────────────────────────────────

async function loadDispatcherPanel() {
  const originSel = $("#disp-origin");
  const areaSel = $("#disp-area");
  const destSel = $("#disp-destination");
  const yardLocs = locations.filter(l => l.location_type === "staging" || l.location_type === "yard");
  const yardOptions = '<option value="">— select —</option>' +
    yardLocs.map(l => `<option value="${l.id}">${l.name}</option>`).join("");
  originSel.innerHTML = yardOptions;
  destSel.innerHTML = yardOptions;
  areaSel.innerHTML = '<option value="">— select area —</option>' +
    switchingAreas.map(a => `<option value="${a.id}">${a.name} (${a.current_car_count ?? 0}/${a.car_capacity})</option>`).join("");

  // Default destination to origin (turn) when origin changes, unless user has set it explicitly
  originSel.addEventListener("change", () => {
    if (!destSel.value) destSel.value = originSel.value;
  });

  try {
    dispatchPlans = await api("GET", "/api/dispatcher/plans") || [];
  } catch {
    dispatchPlans = [];
  }
  renderDispatchPlanList();
}

function renderDispatchPlanList() {
  const container = $("#dispatch-plans-list");
  // Preserve card body expanded state
  const expanded = new Set(
    [...document.querySelectorAll(".consist-body:not(.hidden)")].map(el => el.dataset.planId)
  );
  // Preserve open <details> sections: Set of "planId:section" strings
  const openDetails = new Set(
    [...document.querySelectorAll("details[data-section][open]")]
      .map(el => `${el.dataset.planId}:${el.dataset.section}`)
  );
  if (!dispatchPlans.length) {
    container.innerHTML = '<p class="muted small">No consists built yet.</p>';
    return;
  }
  container.innerHTML = dispatchPlans.map(plan => renderConsistCard(plan)).join("");
  dispatchPlans.forEach(plan => {
    const body = document.querySelector(`.consist-body[data-plan-id="${plan.id}"]`);
    const btn  = document.querySelector(`.consist-toggle[data-plan-id="${plan.id}"]`);
    if (expanded.has(String(plan.id))) {
      body?.classList.remove("hidden");
      if (btn) btn.textContent = "▼";
    }
    // Restore open details
    document.querySelectorAll(`details[data-plan-id="${plan.id}"]`).forEach(el => {
      if (openDetails.has(`${plan.id}:${el.dataset.section}`)) el.open = true;
    });
    wireConsistCard(plan.id);
  });
}

function renderConsistCard(plan) {
  const statusBadgeMap = {
    draft:    '<span class="status-badge status-draft">Ready</span>',
    active:   '<span class="status-badge status-active">active</span>',
    complete: '<span class="status-badge status-complete">complete</span>',
  };
  const statusBadge = statusBadgeMap[plan.status || "draft"] || statusBadgeMap.draft;

  const trainTitle = plan.train_number
    ? `Train #${plan.train_number}`
    : `<em class="muted" style="font-weight:400;font-style:italic">Consist #${plan.id}</em>`;
  const trainName  = plan.train_name ? ` · "${plan.train_name}"` : "";
  const depTime    = plan.departure_time ? `  ${plan.departure_time}` : "";
  const crewParts  = [
    plan.engineer  && `Eng: ${plan.engineer}`,
    plan.conductor && `Cond: ${plan.conductor}`,
  ].filter(Boolean);
  const crew = crewParts.join("  ·  ");

  const instrLabel = { free: "Notes", timetable_train_order: "Train Order", track_warrant: "Track Warrant" }[opsMode] || "Notes";

  const route = plan.origin_name && plan.destination_name
    ? `<div class="muted small consist-route">${plan.origin_name}${plan.switching_area_name ? ` → ${plan.switching_area_name}` : ""} → ${plan.destination_name}</div>`
    : "";

  const assignedElsewhere = new Set(
    dispatchPlans.filter(p => p.id !== plan.id).flatMap(p => (p.power || []).map(c => c.id))
  );
  const caboosesElsewhere = new Set(
    dispatchPlans.filter(p => p.id !== plan.id && p.caboose).map(p => p.caboose.id)
  );
  const locos    = cars.filter(c => c.car_type === "locomotive" && !assignedElsewhere.has(c.id));
  const cabooses = cars.filter(c => c.car_type === "caboose"    && !caboosesElsewhere.has(c.id));
  const assignedPowerIds  = (plan.power || []).map(c => c.id);
  const assignedCabooseId = plan.caboose?.id ?? null;
  const hasPower = assignedPowerIds.length > 0;

  function carRow(c) {
    const imgSrc = c.photo_path ? photoSrc(c.photo_path, c.photo_url) : (defaultCarImage(c.car_type) || null);
    const thumb = imgSrc
      ? `<div class="session-car-thumb"><img src="${imgSrc}" alt="${c.car_type}" /></div>`
      : `<div class="session-car-thumb no-photo-thumb">${c.car_type}</div>`;
    const dest = c.active_waybill?.destination_name || "?";
    const from = c.current_location_name || "?";
    return `
    <div class="session-car-row">
      ${thumb}
      <div class="session-car-info">
        <span class="session-car-marks">${c.reporting_marks || "—"} ${c.car_number || ""} <span class="muted">${c.car_type}</span></span>
        <span class="session-car-move">${c.role === "setout" ? "➡" : "⬅"} ${from} → ${dest}</span>
      </div>
      ${c.active_waybill?.industry_name ? `<span class="industry-tag">${c.active_waybill.industry_name}</span>` : ""}
    </div>`;
  }

  const setouts = plan.setouts || [];
  const pickups = plan.pickups || [];
  const spots   = plan.spots   || [];
  const total   = setouts.length + pickups.length + spots.length;

  let carListHtml = "";
  if (setouts.length) carListHtml += `<p class="muted small" style="margin:0.25rem 0"><strong>Set out</strong></p>` + setouts.map(carRow).join("");
  if (spots.length)   carListHtml += `<p class="muted small" style="margin:0.5rem 0 0.25rem"><strong>Spot locally</strong></p>` + spots.map(carRow).join("");
  if (pickups.length) carListHtml += `<p class="muted small" style="margin:0.5rem 0 0.25rem"><strong>Pick up</strong></p>` + pickups.map(carRow).join("");
  if (!total) carListHtml = '<p class="muted small">No cars in this consist.</p>';

  return `
  <article class="consist-card" data-plan-id="${plan.id}" style="margin-bottom:0.75rem">
    <div class="section-header">
      <div class="section-header-title">
        <button class="outline small consist-toggle" data-plan-id="${plan.id}">▶</button>
        <div>
          <div>${statusBadge} <strong>${trainTitle}${trainName}</strong>${depTime}</div>
          ${crew ? `<div class="muted small" style="font-size:0.8rem">${crew}</div>` : ""}
          ${route}
          ${!hasPower ? `<div class="muted small consist-no-power-hint" style="font-size:0.75rem;color:var(--color-warning,#e07b00)">⚠ No locomotive assigned — open to assign power</div>` : ""}
        </div>
      </div>
      <div class="button-row">
        <button class="consist-start-session" data-plan-id="${plan.id}"${(total === 0 || !hasPower || !!session || plan.status === "complete") ? " disabled" : ""}>Start Session</button>
      </div>
    </div>
    <div class="consist-body hidden" data-plan-id="${plan.id}">

      <details data-section="identity" data-plan-id="${plan.id}" style="margin-top:0.75rem">
        <summary class="muted small" style="cursor:pointer">Edit train identity &amp; crew</summary>
        <div class="grid" style="margin-top:0.5rem">
          <label>Train Number <input type="text" class="consist-train-number" data-plan-id="${plan.id}" value="${plan.train_number || ""}" placeholder="e.g. 42" /></label>
          <label>Train Name <input type="text" class="consist-train-name" data-plan-id="${plan.id}" value="${plan.train_name || ""}" placeholder='e.g. "The Limited"' /></label>
        </div>
        <div class="grid">
          <label>Departure Time <input type="time" class="consist-departure-time" data-plan-id="${plan.id}" value="${plan.departure_time || ""}" /></label>
          <label>Engineer <input type="text" class="consist-engineer" data-plan-id="${plan.id}" value="${plan.engineer || ""}" placeholder="Engineer name" /></label>
        </div>
        <label>Conductor <input type="text" class="consist-conductor" data-plan-id="${plan.id}" value="${plan.conductor || ""}" placeholder="Conductor name" /></label>
        <label>${instrLabel}
          <textarea class="consist-special-instructions" data-plan-id="${plan.id}" rows="3" placeholder="Special instructions…">${plan.special_instructions || ""}</textarea>
        </label>
        <div class="button-row">
          <button class="outline small consist-save-identity" data-plan-id="${plan.id}">Save Identity</button>
        </div>
      </details>

      <details data-section="power" data-plan-id="${plan.id}" style="margin-top:0.5rem">
        <summary class="muted small" style="cursor:pointer">Assign power</summary>
        <div class="grid" style="margin-top:0.5rem">
          <label>Locomotive(s)
            <select multiple size="3" class="consist-power-select" data-plan-id="${plan.id}">
              ${locos.length
                ? locos.map(c => `<option value="${c.id}"${assignedPowerIds.includes(c.id) ? " selected" : ""}>${c.reporting_marks || "—"} ${c.car_number || ""}</option>`).join("")
                : `<option value="" disabled>— no locomotives —</option>`}
            </select>
          </label>
          <label>Caboose
            <select class="consist-caboose-select" data-plan-id="${plan.id}">
              <option value="">— none —</option>
              ${cabooses.map(c => `<option value="${c.id}"${assignedCabooseId === c.id ? " selected" : ""}>${c.reporting_marks || "—"} ${c.car_number || ""}</option>`).join("")}
            </select>
          </label>
        </div>
        <div class="button-row">
          <button class="outline small consist-save-power" data-plan-id="${plan.id}">Save Power</button>
        </div>
      </details>

      <div id="consist-power-strip-${plan.id}">${renderPowerStrip(plan.power, plan.caboose, true)}</div>
      <div id="consist-car-list-${plan.id}">${carListHtml}</div>

      <div class="button-row" style="margin-top:0.75rem;justify-content:flex-end">
        <button class="outline small consist-rebuild" data-plan-id="${plan.id}">↺ Rebuild</button>
        <button class="outline small contrast consist-delete" data-plan-id="${plan.id}">Delete Consist</button>
      </div>
    </div>
  </article>`;
}

function wireConsistCard(planId) {
  const card = document.querySelector(`.consist-card[data-plan-id="${planId}"]`);
  if (!card) return;

  card.querySelector(`.consist-toggle[data-plan-id="${planId}"]`).addEventListener("click", () => {
    const body = card.querySelector(`.consist-body[data-plan-id="${planId}"]`);
    const btn  = card.querySelector(`.consist-toggle[data-plan-id="${planId}"]`);
    const collapsed = body.classList.toggle("hidden");
    btn.textContent = collapsed ? "▶" : "▼";
  });

  const powerSel   = card.querySelector(`.consist-power-select[data-plan-id="${planId}"]`);
  const cabooseSel = card.querySelector(`.consist-caboose-select[data-plan-id="${planId}"]`);

  function liveCardPowerStrip() {
    const powerIds  = [...(powerSel?.selectedOptions || [])].map(o => parseInt(o.value)).filter(v => !isNaN(v));
    const cabooseId = cabooseSel?.value ? parseInt(cabooseSel.value) : null;
    const powerCars  = powerIds.map(id => cars.find(c => c.id === id)).filter(Boolean);
    const cabooseCar = cabooseId ? cars.find(c => c.id === cabooseId) : null;
    const stripEl = document.getElementById(`consist-power-strip-${planId}`);
    if (stripEl) stripEl.innerHTML = renderPowerStrip(powerCars, cabooseCar);
  }
  powerSel?.addEventListener("change",   liveCardPowerStrip);
  cabooseSel?.addEventListener("change", liveCardPowerStrip);

  card.querySelector(`.consist-save-identity[data-plan-id="${planId}"]`).addEventListener("click", async () => {
    const btn = card.querySelector(`.consist-save-identity[data-plan-id="${planId}"]`);
    const body = {
      train_number:         card.querySelector(`.consist-train-number[data-plan-id="${planId}"]`).value.trim() || null,
      train_name:           card.querySelector(`.consist-train-name[data-plan-id="${planId}"]`).value.trim() || null,
      departure_time:       card.querySelector(`.consist-departure-time[data-plan-id="${planId}"]`).value || null,
      engineer:             card.querySelector(`.consist-engineer[data-plan-id="${planId}"]`).value.trim() || null,
      conductor:            card.querySelector(`.consist-conductor[data-plan-id="${planId}"]`).value.trim() || null,
      special_instructions: card.querySelector(`.consist-special-instructions[data-plan-id="${planId}"]`).value.trim() || null,
    };
    try {
      await withLoading(btn, "Saving…", async () => {
        const updated = await api("PATCH", `/api/dispatcher/plan/${planId}/identity`, body);
        const idx = dispatchPlans.findIndex(p => p.id === planId);
        if (idx !== -1) dispatchPlans[idx] = updated;
        renderDispatchPlanList();
        showToast("Train identity saved.", "success");
      });
    } catch (err) {
      showToast("Error saving identity: " + err.message, "error");
    }
  });

  card.querySelector(`.consist-save-power[data-plan-id="${planId}"]`).addEventListener("click", async () => {
    const btn = card.querySelector(`.consist-save-power[data-plan-id="${planId}"]`);
    const powerIds  = [...(powerSel?.selectedOptions || [])].map(o => parseInt(o.value)).filter(v => !isNaN(v));
    const cabooseId = cabooseSel?.value ? parseInt(cabooseSel.value) : null;
    try {
      await withLoading(btn, "Saving…", async () => {
        const updated = await api("PATCH", `/api/dispatcher/plan/${planId}/power`, { power_ids: powerIds, caboose_id: cabooseId });
        const idx = dispatchPlans.findIndex(p => p.id === planId);
        if (idx !== -1) dispatchPlans[idx] = updated;
        renderDispatchPlanList();
        showToast("Power assignment saved.", "success");
      });
    } catch (err) {
      showToast("Error saving power: " + err.message, "error");
    }
  });

  document.getElementById(`consist-power-strip-${planId}`)?.addEventListener("click", async (e) => {
    const btn = e.target.closest(".power-chip-remove");
    if (!btn) return;
    const removeId   = parseInt(btn.dataset.removeId);
    const removeType = btn.dataset.removeType;
    const plan = dispatchPlans.find(p => p.id === planId);
    if (!plan) return;
    const newPowerIds  = removeType === "caboose"
      ? (plan.power || []).map(c => c.id)
      : (plan.power || []).map(c => c.id).filter(id => id !== removeId);
    const newCabooseId = removeType === "caboose" ? null : (plan.caboose?.id ?? null);
    try {
      const updated = await api("PATCH", `/api/dispatcher/plan/${planId}/power`, { power_ids: newPowerIds, caboose_id: newCabooseId });
      const idx = dispatchPlans.findIndex(p => p.id === planId);
      if (idx !== -1) dispatchPlans[idx] = updated;
      renderDispatchPlanList();
      showToast("Power removed.", "success");
    } catch (err) {
      showToast("Error removing power: " + err.message, "error");
    }
  });

  card.querySelector(`.consist-start-session[data-plan-id="${planId}"]`).addEventListener("click", async () => {
    const plan = dispatchPlans.find(p => p.id === planId);
    if (!plan) return;
    const btn = card.querySelector(`.consist-start-session[data-plan-id="${planId}"]`);

    if (session) {
      if (!btn.dataset.confirm) {
        btn.dataset.confirm = "1";
        btn.classList.add("btn-confirming");
        const orig = btn.textContent;
        btn.textContent = "End current session?";
        setTimeout(() => { delete btn.dataset.confirm; btn.classList.remove("btn-confirming"); btn.textContent = orig; }, 4000);
        return;
      }
      btn.classList.remove("btn-confirming");
      delete btn.dataset.confirm;
    }

    try {
      clockState = await api("POST", "/api/session/clock/ensure");
      if (clockState?.started_at) startClockTick();

      try { await api("PATCH", `/api/dispatcher/plan/${planId}/status`, { status: "active" }); } catch {}

      const toSessionCar = (c, group) => ({
        id: c.id,
        marks: `${c.reporting_marks || "—"} ${c.car_number || ""}`.trim(),
        carType: c.car_type,
        fromLocation: c.current_location_name,
        toLocation: c.active_waybill?.destination_name || "?",
        photoPath: c.photo_path || null,
        industryName: c.active_waybill?.industry_name || null,
        toIndustryId: (group !== "departures") ? (c.active_waybill?.industry_id ?? null) : null,
        cpSessions: (group !== "departures") ? (c.cp_session_count || 0) : 0,
        priority: (group !== "departures") ? Math.floor(Math.random() * 1000) : 0,
        group,
        status: "pending",
      });

      const firstLoco = (plan.power || [])[0];
      const locoLabel = firstLoco
        ? `${firstLoco.reporting_marks || ""}${firstLoco.car_number ? " " + firstLoco.car_number : ""}`.trim()
        : "";

      session = {
        planId:              plan.id,
        trainNumber:         plan.train_number || locoLabel || "",
        trainName:           plan.train_name           || "",
        departureTime:       plan.departure_time       || "",
        engineer:            plan.engineer             || "",
        conductor:           plan.conductor            || "",
        specialInstructions: plan.special_instructions || "",
        warnings: plan.warnings || [],
        power:    plan.power    || [],
        caboose:  plan.caboose  || null,
        cars: [
          ...(plan.setouts || []).map(c => toSessionCar(c, "arrivals")),
          ...(plan.spots   || []).map(c => toSessionCar(c, "spots")),
          ...(plan.pickups || []).map(c => toSessionCar(c, "departures")),
        ],
      };
      saveSession();
      renderActiveSession();
      document.querySelector('[data-tab="operations"]').click();
    } catch (err) {
      showToast("Error starting session: " + err.message, "error");
    }
  });

  card.querySelector(`.consist-rebuild[data-plan-id="${planId}"]`).addEventListener("click", async () => {
    const btn = card.querySelector(`.consist-rebuild[data-plan-id="${planId}"]`);
    try {
      await withLoading(btn, "Rebuilding…", async () => {
        const updated = await api("POST", `/api/dispatcher/plan/${planId}/rebuild`);
        const idx = dispatchPlans.findIndex(p => p.id === planId);
        if (idx !== -1) dispatchPlans[idx] = updated;
        renderDispatchPlanList();
        showToast("Consist rebuilt.", "success");
      });
    } catch (err) {
      showToast("Error rebuilding: " + err.message, "error");
    }
  });

  card.querySelector(`.consist-delete[data-plan-id="${planId}"]`).addEventListener("click", async () => {
    const btn = card.querySelector(`.consist-delete[data-plan-id="${planId}"]`);
    if (!btn.dataset.confirm) {
      btn.dataset.confirm = "1";
      btn.classList.add("btn-confirming");
      const orig = btn.textContent;
      btn.textContent = "Confirm delete?";
      setTimeout(() => { delete btn.dataset.confirm; btn.classList.remove("btn-confirming"); btn.textContent = orig; }, 3000);
      return;
    }
    btn.classList.remove("btn-confirming");
    delete btn.dataset.confirm;
    try {
      await api("DELETE", `/api/dispatcher/plan/${planId}`);
      dispatchPlans = dispatchPlans.filter(p => p.id !== planId);
      renderDispatchPlanList();
    } catch (err) {
      showToast("Error deleting consist: " + err.message, "error");
    }
  });
}

$("#btn-build-consist").addEventListener("click", async () => {
  const originId = parseInt($("#disp-origin").value);
  const areaId   = parseInt($("#disp-area").value);
  const destId   = parseInt($("#disp-destination").value);
  if (!originId || !areaId || !destId) { showToast("Select an origin, switching area, and destination first.", "warning"); return; }
  const btn = $("#btn-build-consist");
  await withLoading(btn, "Building…", async () => {
    try {
      const newPlan = await api("POST", "/api/dispatcher/build-plan", {
        origin_location_id: originId,
        switching_area_id: areaId,
        destination_location_id: destId,
      });
      dispatchPlans.push(newPlan);
      renderDispatchPlanList();
      await renderLayoutStatus();
    } catch (err) {
      showToast("Error building consist: " + err.message, "error");
    }
  });
});

$("#btn-clear-all-plans").addEventListener("click", async () => {
  const btn = $("#btn-clear-all-plans");
  if (!btn.dataset.confirm) {
    btn.dataset.confirm = "1";
    btn.classList.add("btn-confirming");
    const orig = btn.textContent;
    btn.textContent = "Clear all — confirm?";
    setTimeout(() => { delete btn.dataset.confirm; btn.classList.remove("btn-confirming"); btn.textContent = orig; }, 3000);
    return;
  }
  btn.classList.remove("btn-confirming");
  delete btn.dataset.confirm;
  try {
    await api("DELETE", "/api/dispatcher/plans");
    dispatchPlans = [];
    renderDispatchPlanList();
  } catch (err) {
    showToast("Error clearing consists: " + err.message, "error");
  }
});

// ── Settings tab ──────────────────────────────────────────────────────────────
async function loadSettings() {
  const data = await api("GET", "/api/tenant-settings");
  if (!data) return;

  const providerSel = $("#settings-provider");
  if (providerSel) providerSel.value = data.vision_provider || "gemini";

  const note = $("#settings-source-note");
  if (note) note.textContent = data.source === "env"
    ? "Running in local dev mode — keys are read from environment variables and cannot be changed here."
    : "";

  const setStatus = (id, field, set) => {
    const el = $(id);
    if (!el) return;
    if (set) {
      el.innerHTML = `✓ Key is set &nbsp;<a href="#" class="clear-key-link" data-field="${field}" style="color:#c0392b;font-size:0.85em;">× Clear</a>`;
    } else {
      el.textContent = "No key configured";
    }
  };
  setStatus("#settings-gemini-status",    "gemini_api_key",    data.gemini_key_set);
  setStatus("#settings-anthropic-status", "anthropic_api_key", data.anthropic_key_set);
  setStatus("#settings-openai-status",    "openai_api_key",    data.openai_key_set);

  const saveBtn = $("#settings-save-btn");
  if (saveBtn && data.source === "env") saveBtn.disabled = true;
}

$("#settings-save-btn")?.addEventListener("click", async () => {
  const msg = $("#settings-save-msg");
  const body = {
    vision_provider: $("#settings-provider")?.value || null,
  };
  const gemini    = $("#settings-gemini-key")?.value;
  const anthropic = $("#settings-anthropic-key")?.value;
  const openai    = $("#settings-openai-key")?.value;
  if (gemini)    body.gemini_api_key    = gemini;
  if (anthropic) body.anthropic_api_key = anthropic;
  if (openai)    body.openai_api_key    = openai;

  const result = await api("PATCH", "/api/tenant-settings", body);
  if (result?.ok) {
    if (msg) msg.textContent = "Saved.";
    ["#settings-gemini-key", "#settings-anthropic-key", "#settings-openai-key"].forEach(id => {
      const el = $(id);
      if (el) el.value = "";
    });
    await loadSettings();
    setTimeout(() => { if (msg) msg.textContent = ""; }, 3000);
  }
});

document.addEventListener("click", async e => {
  const link = e.target.closest(".clear-key-link");
  if (!link) return;
  e.preventDefault();
  const field = link.dataset.field;
  const result = await api("PATCH", "/api/tenant-settings", { [field]: "" });
  if (result?.ok) await loadSettings();
});

$("#invite-send-btn")?.addEventListener("click", async () => {
  const email = $("#invite-email")?.value?.trim();
  const role  = $("#invite-role")?.value || "operator";
  const msg   = $("#invite-msg");
  if (!email) { if (msg) msg.textContent = "Enter an email address."; return; }
  const result = await api("POST", "/api/tenant-settings/invite", { email, role });
  if (result?.ok) {
    if (msg) msg.textContent = `Invite sent to ${email}.`;
    if ($("#invite-email")) $("#invite-email").value = "";
    setTimeout(() => { if (msg) msg.textContent = ""; }, 4000);
  }
});

// ── Bootstrap ─────────────────────────────────────────────────────────────────
(async function init() {
  await Promise.all([
    loadRoster(),
    (async () => {
      [[locations, industries, waybillPool, carTypes, switchingAreas], settings] = await Promise.all([
        Promise.all([
          api("GET", "/api/locations"),
          api("GET", "/api/industries"),
          api("GET", "/api/waybills"),
          api("GET", "/api/car-types"),
          api("GET", "/api/switching-areas"),
        ]),
        api("GET", "/api/settings"),
      ]);
      opsMode = settings?.ops_mode || "free";
      populateCarTypeSelects();
    })(),
  ]);
})();
