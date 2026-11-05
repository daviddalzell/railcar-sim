// SPDX-FileCopyrightText: 2026 David Dalzell
// SPDX-License-Identifier: MIT

/* Rail Car Movement Simulator — frontend */

// ── State ─────────────────────────────────────────────────────────────────────
let commodityMap = [];
let selectedCarId = null;
let editingWaybillId = null;
let stagingMergeDeleteId = null;
let dispatchPlans = [];

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
document.addEventListener("keydown", e => { if (e.key === "Escape") closeAllTreeMenus(); });

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
        const filename = f.path.split("/").pop() || "image.jpg";
        const actions = f.is_default ? "" : `
          <div class="lib-actions">
            <a class="lib-action-btn" href="${f.url}" download="${filename}" title="Download"
               onclick="event.stopPropagation()">⬇</a>
            <button class="lib-action-btn lib-delete-btn" data-path="${f.path}" title="Delete"
                    onclick="event.stopPropagation()">🗑</button>
          </div>`;
        return `
        <div class="lib-thumb${f.assigned ? " lib-assigned" : ""}${sel}"
             data-path="${f.path}" data-url="${f.url}" data-is-default="${f.is_default}">
          <img src="${f.url}" alt="" loading="lazy" />
          ${badge}${actions}
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
    grid.innerHTML = err.status === 401
      ? `<p class="muted" style="text-align:center">Sign in to access your photo library.</p>`
      : `<p class="muted" style="text-align:center">Failed to load library: ${err.message}</p>`;
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

// ── Roster ────────────────────────────────────────────────────────────────────
async function loadRoster() {
  appState.cars = await api("GET", "/api/cars");
  renderCarGrid();
}

function defaultCarImage(carTypeName) {
  const ct = appState.carTypes.find(t => t.name === carTypeName);
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
  const locos   = appState.cars.filter(c => c.car_type === "locomotive");
  const freight = appState.cars.filter(c => c.car_type !== "locomotive");

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
  const orphaned = appState.cars.filter(c => c.current_location_id && !c.current_location_name);
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
    appState.cars = await api("GET", "/api/cars");
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
    const result = await api("POST", "/api/cars/stylize", { photo_path: appState.photoPath });
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
  appState.photoPath = null;
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
  appState.photoPath = null;
  $("#photo-input").value = "";
  $("#upload-label").textContent = "📷 Click or drop a photo (optional)";
  $("#field-marks").value = "";
  $("#field-number").value = "";
  $("#field-type").value = "other";
  $("#field-color").value = "";
  updateDefaultImageOffer();
});

async function cancelAddCar() {
  await discardStylized();
  hide($("#add-car-form"));
  hide($("#stylize-section"));
  hide($("#default-image-offer"));
}
$("#btn-cancel-car").addEventListener("click", cancelAddCar);
$("#btn-cancel-car-top").addEventListener("click", cancelAddCar);

function applyAnalysis(result) {
  if (result.photo_path) appState.photoPath = result.photo_path;
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
    appState.photoPath = stylizedPath;
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
      appState.photoPath = path;
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
      appState.photoPath = path;
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
        appState.photoPath = result.photo_path;
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
    const result = await api("POST", "/api/cars/analyze-photo", { photo_path: appState.photoPath });
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
    photo_path: appState.photoPath || "",
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
  const car = appState.cars.find(c => c.id === carId);
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
      const idx = appState.cars.findIndex(c => c.id === selectedCarId);
      if (idx !== -1) appState.cars[idx] = updated;
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
  const car = appState.cars.find(c => c.id === selectedCarId);
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
    appState.locations.map(l => `<option value="${l.id}">${l.name} (${l.location_type})</option>`).join("");
  const car = appState.cars.find(c => c.id === selectedCarId);
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
    const idx = appState.cars.findIndex(c => c.id === selectedCarId);
    if (idx !== -1) appState.cars[idx] = updated;
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

  const current = appState.waybillPool.filter(w => w.id === currentWaybillId);
  const primary  = appState.waybillPool.filter(w => w.id !== currentWaybillId && typeMatches(w) && originMatches(w));
  const fallback = primary.length === 0
    ? appState.waybillPool.filter(w => w.id !== currentWaybillId && typeMatches(w))
    : [];

  const opts = list => list.map(w => `<option value="${w.id}">${label(w)}</option>`).join("");

  return '<option value="">— empty —</option>' +
    opts(current) +
    opts(primary) +
    (fallback.length ? `<optgroup label="other locations">${opts(fallback)}</optgroup>` : "");
}

function getSelectedSlotWaybill(slotIndex) {
  const sel = $(`[data-slot="${slotIndex}"].slot-picker`, $("#waybill-slots"));
  return sel?.value ? appState.waybillPool.find(w => w.id === parseInt(sel.value)) : null;
}

function refreshSlot(slotIndex, carType) {
  const sel = $(`[data-slot="${slotIndex}"].slot-picker`, $("#waybill-slots"));
  if (!sel) return;
  const currentVal = sel.value ? parseInt(sel.value) : null;
  const prevWb = slotIndex > 0 ? getSelectedSlotWaybill(slotIndex - 1) : null;
  const expectedOriginId = slotIndex === 0
    ? (appState.cars.find(c => c.id === selectedCarId)?.current_location_id ?? null)
    : (prevWb?.destination_id ?? null);
  sel.innerHTML = buildSlotOptions(expectedOriginId, carType, currentVal);
  sel.value = currentVal || "";
}

$("#btn-edit-waybills").addEventListener("click", async () => {
  if (!selectedCarId) return;
  const car = appState.cars.find(c => c.id === selectedCarId);
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
    appState.cars = updated;
    renderCarGrid();
    $("#waybill-dialog").close();
    await openCarDetail(selectedCarId);
  } catch (err) {
    showToast("Error saving waybills: " + err.message, "error");
  }
});

// ── Waybill pool ──────────────────────────────────────────────────────────────
async function loadWaybillPool() {
  appState.waybillPool = await api("GET", "/api/waybills");
  renderWaybillPool();
}

function renderWaybillPool() {
  const list = $("#waybill-pool-list");
  if (!appState.waybillPool.length) {
    list.innerHTML = emptyState("➡️", "No waybills yet — generate from industries or add one manually.");
    return;
  }
  list.innerHTML = appState.waybillPool.map(w => `
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
        <button class="icon-btn edit-wb" data-id="${w.id}">✏️</button>
        <button class="icon-btn del-wb" data-id="${w.id}">🗑</button>
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

// Build track <option> markup grouped by Location group via <optgroup>.
// placeholderHtml is the leading empty option. filterFn selects which tracks appear.
function buildTrackOptgroups(placeholderHtml, filterFn = () => true) {
  const grouped = appState.switchingAreas.map(g => {
    const tracks = appState.locations.filter(l => l.location_id === g.id && filterFn(l));
    if (!tracks.length) return "";
    return `<optgroup label="${g.name}">${tracks.map(l => `<option value="${l.id}">${l.name}</option>`).join("")}</optgroup>`;
  }).join("");
  const ungrouped = appState.locations.filter(l => !l.location_id && filterFn(l))
    .map(l => `<option value="${l.id}">${l.name}</option>`).join("");
  return placeholderHtml + grouped + ungrouped;
}

function openWaybillEditDialog(waybillId = null) {
  editingWaybillId = waybillId;
  const w = waybillId ? appState.waybillPool.find(x => x.id === waybillId) : null;
  $("#waybill-edit-title").textContent = w ? "Edit Waybill" : "New Waybill";

  $("#we-name").value = w?.name || "";
  $("#we-commodity").value = w?.commodity || "";
  $("#we-empty").checked = w?.is_empty || false;

  const buildTrackOptions = () => buildTrackOptgroups('<option value="">—</option>');
  const buildIndOptions = () => {
    const grouped = appState.switchingAreas.map(g => {
      const tracks = appState.locations.filter(l => l.location_id === g.id);
      const inds = appState.industries.filter(i => tracks.some(t => t.id === i.location_id));
      if (!inds.length) return "";
      return `<optgroup label="${g.name}">${inds.map(i => `<option value="${i.id}">${i.name}</option>`).join("")}</optgroup>`;
    }).join("");
    const ungroupedInds = appState.industries.filter(i => {
      const track = appState.locations.find(l => l.id === i.location_id);
      return !track?.location_id;
    }).map(i => `<option value="${i.id}">${i.name}</option>`).join("");
    return '<option value="">—</option>' + grouped + ungroupedInds;
  };
  $("#we-origin").innerHTML = buildTrackOptions();
  $("#we-destination").innerHTML = buildTrackOptions();
  $("#we-industry").innerHTML = buildIndOptions();

  if (w?.origin_id) $("#we-origin").value = w.origin_id;
  if (w?.destination_id) $("#we-destination").value = w.destination_id;
  if (w?.industry_id) $("#we-industry").value = w.industry_id;
  $("#we-car-type").value = w?.required_car_type || "";
  $("#we-is-priority").checked = w?.is_priority || false;

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
      appState.cars = result.cars_updated;
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
    is_priority: $("#we-is-priority").checked,
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
