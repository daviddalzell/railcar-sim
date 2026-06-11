/* Rail Car Movement Simulator — frontend */

// ── State ─────────────────────────────────────────────────────────────────────
let locations = [];
let industries = [];
let cars = [];
let waybillPool = [];
let commodityMap = [];
let selectedCarId = null;
let editingWaybillId = null;
let photoPath = null;

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
  const container = $("#toast-container");
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

$("#close-photo-library-dialog").addEventListener("click", () => $("#photo-library-dialog").close());
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

$("#btn-cancel-car").addEventListener("click", () => {
  hide($("#add-car-form"));
  hide($("#stylize-section"));
  stylizedPath = null;
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
$("#btn-stylize").addEventListener("click", runStylize);
$("#btn-regenerate").addEventListener("click", runStylize);

$("#btn-use-stylized").addEventListener("click", () => {
  if (stylizedPath) {
    photoPath = stylizedPath;
    $("#preview-img").src = $("#stylize-preview").src;
  }
  hide($("#stylize-section"));
});

$("#btn-keep-original").addEventListener("click", () => {
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

$("#photo-input").addEventListener("change", async e => {
  const file = e.target.files[0];
  if (!file) return;

  $("#upload-label").textContent = file.name;
  $("#preview-img").src = URL.createObjectURL(file);
  show($("#upload-preview"));
  hide($("#vision-error"));

  const form = new FormData();
  form.append("file", file);

  if (addMode === "manual") {
    // Just upload the file, no vision analysis
    try {
      const result = await api("POST", "/api/cars/upload", form);
      if (result.photo_path) photoPath = result.photo_path;
    } catch (err) {
      $("#vision-error-msg").textContent = "Upload failed: " + err.message;
      show($("#vision-error"));
    }
    return;
  }

  // Photo mode: upload then analyze
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
});

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
    const orig = btn.textContent;
    btn.textContent = "Confirm delete?";
    setTimeout(() => { delete btn.dataset.confirm; btn.textContent = orig; }, 3000);
    return;
  }
  delete btn.dataset.confirm;
  try {
    await api("DELETE", `/api/cars/${selectedCarId}`);
    $("#car-detail-dialog").close();
    await loadRoster();
    showToast("Car deleted.", "warn");
  } catch (err) {
    showToast("Error: " + err.message, "error");
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
    list.innerHTML = emptyState("📋", "No waybills yet — generate from industries or add one manually.");
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
        const orig = btn.innerHTML;
        btn.textContent = "Sure?";
        setTimeout(() => { delete btn.dataset.confirm; btn.innerHTML = orig; }, 3000);
        return;
      }
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
    const orig = btn.textContent;
    btn.textContent = "Replace all — confirm?";
    setTimeout(() => { delete btn.dataset.confirm; btn.textContent = orig; }, 4000);
    return;
  }
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
              group: "arrivals",
              status: "pending",
            })),
            ...plan.departures.map(c => ({
              id: c.id,
              marks: `${c.reporting_marks || "—"} ${c.car_number || ""}`.trim(),
              carType: c.car_type,
              fromLocation: c.session_from_location_name,
              toLocation: c.session_to_location_name,
              group: "departures",
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
    const instruction = wb
      ? `${wb.is_empty ? "Move <strong>empty</strong>" : `Move with <strong>${wb.commodity || "load"}</strong>`} from <em>${wb.origin_name || "?"}</em> to <em>${wb.destination_name || "?"}</em>${wb.industry_name ? ` (${wb.industry_name})` : ""}`
      : `<span class='muted'>No waybill assigned</span>`;
    return `
      <div class="ops-row${needsMove ? ' car-needs-move' : ''}">
        <div class="ops-thumb">
          ${car.photo_path ? `<img src="/${car.photo_path}" />` : `<div class="no-photo small">${car.car_type}</div>`}
        </div>
        <div class="ops-info">
          <strong>${car.reporting_marks || "—"} ${car.car_number || ""}</strong>
          <span class="car-type">${car.car_type} · ${car.color}</span>
          <span>📍 ${car.current_location_name || "Unassigned"}</span>
          <span class="instruction">${instruction}</span>
        </div>
        <div class="ops-actions">
          <span class="slot-badge">Card ${(car.active_waybill_slot ?? 0) + 1}</span>
        </div>
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
  document.getElementById("btn-cancel-session").addEventListener("click", () => {
    const btn = document.getElementById("btn-cancel-session");
    if (!btn.dataset.confirm) {
      btn.dataset.confirm = "1";
      const orig = btn.textContent;
      btn.textContent = "Abandon session?";
      setTimeout(() => { delete btn.dataset.confirm; btn.textContent = orig; }, 3000);
      return;
    }
    session = null;
    saveSession();
    loadOperations();
  });

  const arrivals   = session.cars.filter(c => c.group === "arrivals");
  const departures = session.cars.filter(c => c.group === "departures");

  function carRow(car) {
    const statusClass = car.status === "done" ? " done" : car.status === "cp" ? " cp" : "";
    return `
      <div class="session-car-row${statusClass}" id="session-row-${car.id}">
        <div class="session-car-info">
          <span class="session-car-marks">${car.marks} <span class="muted">${car.carType}</span></span>
          <span class="session-car-move">📍 ${car.fromLocation || "?"} → ${car.toLocation || "?"}</span>
        </div>
        <div class="session-btn-row">
          <button class="outline small session-done-btn${car.status === "done" ? " active-btn" : ""}" data-id="${car.id}">✓ Done</button>
          <button class="outline small session-cp-btn${car.status === "cp" ? " active-btn" : ""}" data-id="${car.id}">✗ CP</button>
        </div>
      </div>`;
  }

  const noWork = !arrivals.length && !departures.length;
  let html = "";
  if (noWork) {
    html = `<p class="muted" style="text-align:center;padding:1.5rem">No cars to work this session.</p>`;
  } else {
    if (arrivals.length) {
      html += `<p class="session-section-title">Set out from staging (${arrivals.length})</p>`;
      html += arrivals.map(carRow).join("");
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
  [locations, industries, commodityMap] = await Promise.all([
    api("GET", "/api/locations"),
    api("GET", "/api/industries"),
    api("GET", "/api/commodity-car-type-map"),
  ]);
  renderLocationList();
  renderIndustryList();
  populateIndustryLocationSelect();
  renderCommodityMapList();
}

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
        const orig = btn.innerHTML;
        btn.textContent = "Sure?";
        setTimeout(() => { delete btn.dataset.confirm; btn.innerHTML = orig; }, 3000);
        return;
      }
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

function roleToCheckboxes(role) {
  $("#ind-receiver").checked = (role !== "producer");
  $("#ind-shipper").checked  = (role === "producer" || role === "transload");
}

function renderIndustryList() {
  const list = $("#industry-list");
  if (!industries.length) {
    list.innerHTML = emptyState("🏭", "No industries yet — add one with the + button.");
    return;
  }
  const roleBadge = r => r === "producer" ? "producer" : r === "transload" ? "transload" : "";
  list.innerHTML = industries.map(i => `
    <div class="layout-item">
      <span>
        <strong>${i.name}</strong>
        ${i.location_name ? `<em>@ ${i.location_name}</em>` : ""}
        ${roleBadge(i.industry_role) ? `<span class='waybill-badge muted'>${roleBadge(i.industry_role)}</span>` : ""}
        ${i.commodities ? `<span class='muted'>${i.commodities}</span>` : ""}
      </span>
      <span>
        <button class="outline small edit-ind" data-id="${i.id}">✏️</button>
        <button class="outline small contrast del-ind" data-id="${i.id}">🗑</button>
      </span>
    </div>
  `).join("");

  $$(".edit-ind").forEach(btn => {
    btn.addEventListener("click", () => {
      const ind = industries.find(i => i.id === parseInt(btn.dataset.id));
      if (!ind) return;
      $("#ind-name").value = ind.name;
      $("#ind-location").value = ind.location_id || "";
      $("#ind-car-types").value = ind.accepted_car_types;
      $("#ind-commodities").value = ind.commodities;
      $("#ind-edit-id").value = ind.id;
      roleToCheckboxes(ind.industry_role || "consumer");
      show($("#industry-form"));
    });
  });

  $$(".del-ind").forEach(btn => {
    btn.addEventListener("click", async () => {
      if (!btn.dataset.confirm) {
        btn.dataset.confirm = "1";
        const orig = btn.innerHTML;
        btn.textContent = "Sure?";
        setTimeout(() => { delete btn.dataset.confirm; btn.innerHTML = orig; }, 3000);
        return;
      }
      delete btn.dataset.confirm;
      try {
        await api("DELETE", `/api/industries/${btn.dataset.id}`);
        await loadLayout();
      } catch (err) {
        showToast("Error: " + err.message, "error");
      }
    });
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
  $("#ind-car-types").value = "";
  $("#ind-commodities").value = "";
  $("#ind-edit-id").value = "";
  roleToCheckboxes("consumer");
  show($("#industry-form"));
});
$("#btn-cancel-industry").addEventListener("click", () => hide($("#industry-form")));

$("#industry-form").addEventListener("submit", async e => {
  e.preventDefault();
  const editId = $("#ind-edit-id").value;
  const locVal = $("#ind-location").value;
  const body = {
    name: $("#ind-name").value.trim(),
    location_id: locVal ? parseInt(locVal) : null,
    accepted_car_types: $("#ind-car-types").value.trim(),
    commodities: $("#ind-commodities").value.trim(),
    industry_role: checkboxesToRole(),
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
{
  const input    = $("#ind-commodities");
  const dropdown = $("#commodity-suggestions");
  const warnEl   = $("#commodity-warn");

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
    warnEl.classList.add("hidden");
    if (!token || !commodityMap.length) { dropdown.classList.add("hidden"); return; }
    const matches = commodityMap.filter(m => m.commodity.includes(token));
    if (!matches.length) { dropdown.classList.add("hidden"); return; }
    dropdown.innerHTML = matches.map(m =>
      `<li class="suggestion-item" data-commodity="${m.commodity}">
        <span>${m.commodity}</span>
        <span class="suggestion-car-type">${m.car_type}</span>
      </li>`
    ).join("");
    dropdown.querySelectorAll(".suggestion-item").forEach(li =>
      li.addEventListener("mousedown", e => { e.preventDefault(); completeToken(li.dataset.commodity); })
    );
    dropdown.classList.remove("hidden");
  });

  input.addEventListener("blur", () => {
    dropdown.classList.add("hidden");
    const tokens = input.value.split(",").map(t => t.trim().toLowerCase()).filter(Boolean);
    const unknown = tokens.filter(t => !commodityMap.find(m => m.commodity === t));
    if (unknown.length) {
      warnEl.textContent = `⚠ Not in commodity map: ${unknown.join(", ")}`;
      warnEl.classList.remove("hidden");
    }
  });
}

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
        const orig = btn.innerHTML;
        btn.textContent = "Sure?";
        setTimeout(() => { delete btn.dataset.confirm; btn.innerHTML = orig; }, 3000);
        return;
      }
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
$("#btn-import-trigger").addEventListener("click", () => {
  const btn = $("#btn-import-trigger");
  if (!btn.dataset.confirm) {
    btn.dataset.confirm = "1";
    const orig = btn.textContent;
    btn.textContent = "⚠ Replace ALL data? Click again.";
    setTimeout(() => { delete btn.dataset.confirm; btn.textContent = orig; }, 5000);
    return;
  }
  delete btn.dataset.confirm;
  btn.textContent = "⬆ Import Backup";
  $("#import-file-input").click();
});

$("#btn-purge-uploads").addEventListener("click", async () => {
  const btn = $("#btn-purge-uploads");
  if (!btn.dataset.confirm) {
    btn.dataset.confirm = "1";
    const orig = btn.textContent;
    btn.textContent = "⚠ Delete unassigned? Click again.";
    setTimeout(() => { delete btn.dataset.confirm; btn.textContent = orig; }, 4000);
    return;
  }
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

// ── Bootstrap ─────────────────────────────────────────────────────────────────
(async function init() {
  await Promise.all([
    loadRoster(),
    (async () => {
      [locations, industries, waybillPool] = await Promise.all([
        api("GET", "/api/locations"),
        api("GET", "/api/industries"),
        api("GET", "/api/waybills"),
      ]);
    })(),
  ]);
})();
