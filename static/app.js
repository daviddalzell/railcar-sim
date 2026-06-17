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

// ── Fast clock ────────────────────────────────────────────────────────────────
let clockInterval = null;
let clockState = null;

async function fetchAndStartClock() {
  clockState = await api("GET", "/api/session/clock");
  if (clockState?.started_at) startClockTick();
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
  const btn = $("#btn-clock-pause");
  if (!clockState) return;
  if (clockState.paused_at) {
    clockState = await api("POST", "/api/session/clock/resume");
    startClockTick();
    if (btn) btn.textContent = "⏸";
  } else {
    clockState = await api("POST", "/api/session/clock/pause");
    if (btn) btn.textContent = "▶";
  }
}

// ── Helpers ───────────────────────────────────────────────────────────────────
const $ = (sel, ctx = document) => ctx.querySelector(sel);
const $$ = (sel, ctx = document) => [...ctx.querySelectorAll(sel)];

async function api(method, path, body) {
  const opts = { method, headers: {} };
  if (body && !(body instanceof FormData)) {
    opts.headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(body);
  } else if (body) {
    opts.body = body;
  }
  const res = await fetch(path, opts);
  if (res.status === 204) return null;
  let data;
  try {
    data = await res.json();
  } catch {
    throw new Error(`Server error (${res.status})`);
  }
  if (!res.ok) throw new Error(data.detail || "Request failed");
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

async function openPhotoLibrary(onSelect) {
  photoLibraryCallback = onSelect;
  const grid = $("#photo-library-grid");
  grid.innerHTML = `<p class="muted" style="text-align:center;padding:1rem"><span class="spinner"></span>Loading…</p>`;
  $("#photo-library-dialog").showModal();
  try {
    const files = await api("GET", "/api/uploads");
    if (!files.length) {
      grid.innerHTML = emptyState("🖼", "No photos uploaded yet.");
    } else {
      grid.innerHTML = files.map(f => `
        <div class="lib-thumb${f.assigned ? " lib-assigned" : ""}" data-path="${f.path}" data-url="${f.url}">
          <img src="${f.url}" alt="" loading="lazy" />
          ${f.assigned ? '<span class="lib-badge">in use</span>' : ""}
        </div>
      `).join("");
      $$(".lib-thumb").forEach(el => {
        el.addEventListener("click", () => {
          photoLibraryCallback({ path: el.dataset.path, url: el.dataset.url });
          $("#photo-library-dialog").close();
        });
      });
    }
  } catch (err) {
    grid.innerHTML = `<p class="muted" style="text-align:center">Failed to load library: ${err.message}</p>`;
  }
}

$("#btn-close-library").addEventListener("click", () => $("#photo-library-dialog").close());

// ── Tab navigation ────────────────────────────────────────────────────────────
$$(".tab-link").forEach(link => {
  link.addEventListener("click", e => {
    e.preventDefault();
    const tab = link.dataset.tab;
    $$(".tab-link").forEach(l => l.classList.remove("active"));
    $$(".tab-panel").forEach(p => p.classList.add("hidden"));
    link.classList.add("active");
    $(`#tab-${tab}`).classList.remove("hidden");
    if (tab === "operations") loadOperations();
    if (tab === "waybills") loadWaybillPool();
    if (tab === "layout") loadLayout();
  });
});

// ── Roster ────────────────────────────────────────────────────────────────────
async function loadRoster() {
  cars = await api("GET", "/api/cars");
  renderCarGrid();
}

function renderCarGrid() {
  const grid = $("#car-grid");
  if (!cars.length) {
    grid.innerHTML = emptyState("🚃", "No cars yet — add one with the buttons above.");
    return;
  }
  grid.innerHTML = cars.map(car => {
    const needsMove = car.active_waybill
      && car.active_waybill.destination_id != null
      && car.current_location_id !== car.active_waybill.destination_id;
    return `
    <div class="car-card${needsMove ? ' car-needs-move' : ''}" data-id="${car.id}">
      <div class="car-thumb">
        ${car.photo_path
          ? `<img src="/${car.photo_path}" alt="${car.reporting_marks} ${car.car_number}" />`
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
  `; }).join("");

  $$(".car-card").forEach(card => {
    card.addEventListener("click", () => openCarDetail(parseInt(card.dataset.id)));
  });
}

// ── Add car via photo ─────────────────────────────────────────────────────────
let addMode = "photo"; // "photo" | "manual"
let stylizedPath = null;

function showStylizeIdle() {
  show($("#stylize-idle"));
  hide($("#stylize-processing"));
  hide($("#stylize-result"));
  hide($("#stylize-error"));
}

async function runStylize() {
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
    $("#stylize-error-msg").textContent = "Stylize failed: " + err.message;
    show($("#stylize-error"));
    show($("#stylize-idle"));
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
  show($("#car-fields"));
  photoPath = null;
  $("#photo-input").value = "";
  $("#upload-label").textContent = "📷 Click or drop a photo (optional)";
  $("#field-marks").value = "";
  $("#field-number").value = "";
  $("#field-type").value = "other";
  $("#field-color").value = "";
});

$("#btn-cancel-car").addEventListener("click", async () => {
  await discardStylized();
  hide($("#add-car-form"));
  hide($("#stylize-section"));
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

async function processPhotoFile(file) {
  if (!file) return;

  $("#upload-label").textContent = file.name;
  $("#preview-img").src = URL.createObjectURL(file);
  show($("#upload-preview"));
  hide($("#vision-error"));

  const form = new FormData();
  form.append("file", file);

  if (addMode === "manual") {
    try {
      const result = await api("POST", "/api/cars/upload", form);
      if (result.photo_path) photoPath = result.photo_path;
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

  $("#detail-body").innerHTML = `
    <div class="detail-grid">
      ${car.photo_path ? `<img src="/${car.photo_path}" class="detail-photo" />` : ""}
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
    preview.src = "/" + car.photo_path;
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
    const result = await fetch("/api/cars/upload?skip_analysis=true", { method: "POST", body: fd })
      .then(r => r.json());
    if (result.photo_path) {
      $("#edit-photo-path").value = result.photo_path;
      const preview = $("#edit-photo-preview");
      preview.src = "/" + result.photo_path;
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

$("#btn-edit-waybills").addEventListener("click", async () => {
  if (!selectedCarId) return;
  const car = cars.find(c => c.id === selectedCarId);
  const assigned = await api("GET", `/api/cars/${selectedCarId}/waybills`);
  const bySlot = {};
  assigned.forEach(w => { bySlot[w.slot_index] = w; });

  const activeSlot = car?.active_waybill_slot ?? 0;
  $("#waybill-dialog-title").textContent = `Assign Waybills — ${car?.reporting_marks || ""} ${car?.car_number || ""}`;

  const poolOptions = '<option value="">— empty —</option>' +
    waybillPool.map(w => `<option value="${w.id}">${w.name || w.id}${w.origin_name ? ` (${w.origin_name} → ${w.destination_name || "?"})` : ""}</option>`).join("");

  $("#waybill-slots").innerHTML = Array.from({ length: SLOT_COUNT }, (_, i) => {
    const current = bySlot[i];
    return `
      <div class="slot-assign-row ${i === activeSlot ? "active-slot" : ""}">
        <span class="slot-num">${i + 1}${i === activeSlot ? " ★" : ""}</span>
        <select data-slot="${i}" class="slot-picker">${poolOptions}</select>
      </div>
    `;
  }).join("");

  // Pre-select currently assigned waybills
  assigned.forEach(w => {
    const sel = $(`[data-slot="${w.slot_index}"].slot-picker`, $("#waybill-slots"));
    if (sel) sel.value = w.id;
  });

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
  const sel = $("#gen-origin-location");
  sel.innerHTML = '<option value="">— pick a location —</option>' +
    locations.map(l => `<option value="${l.id}">${l.name} (${l.location_type})</option>`).join("");
  $("#generate-waybills-dialog").showModal();
});

$("#close-generate-dialog").addEventListener("click", () => $("#generate-waybills-dialog").close());
$("#btn-cancel-generate").addEventListener("click", () => $("#generate-waybills-dialog").close());

$("#btn-confirm-generate").addEventListener("click", async () => {
  const originId = $("#gen-origin-location").value;
  if (!originId) { showToast("Please select an origin location.", "warn"); return; }
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
      const result = await api("POST", "/api/generate-waybills", { origin_location_id: parseInt(originId), replace });
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

  if (session) {
    // Active session: swap header buttons and render switch list
    $("#ops-header-buttons").innerHTML = ""; // cleared by renderActiveSession
    renderActiveSession();
    return;
  }

  $("#ops-title").textContent = "Operations";
  // Idle state: show Plan Session button + read-only amber list
  $("#ops-header-buttons").innerHTML =
    `<button id="btn-plan-session">🚆 Plan Session</button>`;
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
              industryName: c.active_waybill?.industry_name || null,
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
              industryName: c.active_waybill?.industry_name || null,
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
              industryName: c.active_waybill?.industry_name || null,
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
    const thumb = car.photo_path
      ? `<div class="session-car-thumb clickable-thumb" data-id="${car.id}"><img src="/${car.photo_path}" alt="" /></div>`
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
  renderActiveSession();
}

function renderActiveSession() {
  $("#ops-title").textContent = "Active Session";
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
    <div class="fast-clock">
      <span id="clock-time">--:--</span>
      <button id="btn-clock-pause" class="outline clock-btn" title="Pause / Resume clock">⏸</button>
    </div>
    <button id="btn-cancel-session" class="outline secondary">✕ Cancel Session</button>
    <button id="btn-end-session" class="contrast">⬛ End Session</button>
  `;
  document.getElementById("btn-end-session").addEventListener("click", handleEndSession);
  document.getElementById("btn-clock-pause").addEventListener("click", toggleClockPause);
  document.getElementById("btn-cancel-session").addEventListener("click", () => {
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
    session = null;
    saveSession();
    loadOperations();
  });

  const arrivals   = session.cars.filter(c => c.group === "arrivals");
  const departures = session.cars.filter(c => c.group === "departures");
  const spots      = session.cars.filter(c => c.group === "spots");

  function carRow(car) {
    const statusClass = car.status === "done" ? " done" : car.status === "cp" ? " cp" : "";
    const thumb = car.photoPath
      ? `<div class="session-car-thumb clickable-thumb" data-id="${car.id}"><img src="/${car.photoPath}" alt="" /></div>`
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

  const noWork = !arrivals.length && !departures.length && !spots.length;
  let html = "";
  if (noWork) {
    html = `<p class="muted" style="text-align:center;padding:1.5rem">No cars to work this session.</p>`;
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

  fetchAndStartClock();
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
  [[locations, industries, commodityMap, carTypes], settings] = await Promise.all([
    Promise.all([
      api("GET", "/api/locations"),
      api("GET", "/api/industries"),
      api("GET", "/api/commodity-car-type-map"),
      api("GET", "/api/car-types"),
    ]),
    api("GET", "/api/settings"),
  ]);
  renderLocationList();
  renderIndustryList();
  populateIndustryLocationSelect();
  renderCommodityMapList();
  populateCarTypeSelects();
  renderCarTypeList();
  if (settings) {
    $("#clock-start-time").value = settings.clock_start_time;
    $("#clock-speed").value = String(settings.clock_speed);
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

function renderCarTypeList() {
  const list = $("#car-type-list");
  if (!carTypes.length) {
    list.innerHTML = '<p class="muted small">No car types defined.</p>';
    return;
  }
  list.innerHTML = carTypes.map(ct => `
    <div class="layout-item">
      <span>${ct.name}</span>
      <button class="outline small contrast del-car-type" data-id="${ct.id}" data-name="${ct.name}">🗑</button>
    </div>
  `).join("");
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
  await api("PUT", "/api/settings", {
    clock_start_time: $("#clock-start-time").value,
    clock_speed: parseInt($("#clock-speed").value),
  });
  showToast("Clock settings saved.", "success");
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
      $("#loc-edit-id").value = loc.id;
      show($("#location-form"));
    });
  });

  $$(".del-loc").forEach(btn => {
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
        await api("DELETE", `/api/locations/${btn.dataset.id}`);
        await loadLayout();
      } catch (err) {
        showToast("Error: " + err.message, "error");
      }
    });
  });
}

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
      $("#ind-inbound-car-types").value = ind.inbound_car_types || ind.accepted_car_types || "";
      $("#ind-inbound-commodities").value = ind.commodities || "";
      $("#ind-outbound-car-types").value = ind.outbound_car_types || "";
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

function populateIndustryLocationSelect() {
  const sel = $("#ind-location");
  sel.innerHTML = '<option value="">— no location —</option>' +
    locations.map(l => `<option value="${l.id}">${l.name}</option>`).join("");
}

$("#btn-add-location").addEventListener("click", () => {
  $("#loc-name").value = "";
  $("#loc-type").value = "yard";
  $("#loc-edit-id").value = "";
  show($("#location-form"));
});
$("#btn-cancel-location").addEventListener("click", () => hide($("#location-form")));

$("#location-form").addEventListener("submit", async e => {
  e.preventDefault();
  const editId = $("#loc-edit-id").value;
  const body = {
    name: $("#loc-name").value.trim(),
    location_type: $("#loc-type").value,
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
  $("#ind-inbound-car-types").value = "";
  $("#ind-inbound-commodities").value = "";
  $("#ind-outbound-car-types").value = "";
  $("#ind-outbound-commodities").value = "";
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
    if (result.inbound_car_types)    $("#ind-inbound-car-types").value    = result.inbound_car_types;
    if (result.outbound_commodities) $("#ind-outbound-commodities").value = result.outbound_commodities;
    if (result.outbound_car_types)   $("#ind-outbound-car-types").value   = result.outbound_car_types;
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
  const body = {
    name: $("#ind-name").value.trim(),
    location_id: locVal ? parseInt(locVal) : null,
    accepted_car_types: "",
    commodities: $("#ind-inbound-commodities").value.trim(),
    industry_role: checkboxesToRole(),
    inbound_car_types: $("#ind-inbound-car-types").value.trim(),
    outbound_commodities: $("#ind-outbound-commodities").value.trim(),
    outbound_car_types: $("#ind-outbound-car-types").value.trim(),
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
          inbound_car_types: $("#ind-inbound-car-types").value.trim(),
          outbound_commodities: $("#ind-outbound-commodities").value.trim(),
          outbound_car_types: $("#ind-outbound-car-types").value.trim(),
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
    const result = await fetch("/api/import/cars", { method: "POST", body: fd }).then(async r => {
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
    const resp = await fetch("/api/import/cars/commit", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
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

// ── Bootstrap ─────────────────────────────────────────────────────────────────
(async function init() {
  await Promise.all([
    loadRoster(),
    (async () => {
      [locations, industries, waybillPool, carTypes] = await Promise.all([
        api("GET", "/api/locations"),
        api("GET", "/api/industries"),
        api("GET", "/api/waybills"),
        api("GET", "/api/car-types"),
      ]);
      populateCarTypeSelects();
    })(),
  ]);
})();
