// SPDX-FileCopyrightText: 2026 David Dalzell
// SPDX-License-Identifier: MIT

// Roster grid (Car Roster tab) and the Car detail dialog (incl. Edit car,
// Move car, Per-car auto-assign, Assign waybill slots). Loaded as a classic
// script before app.js. renderCarGrid/loadRoster/defaultCarImage are called
// from add-car.js, layout.js, operations.js, and app.js's Bootstrap init();
// openCarDetail is called from app.js's #ops-list click listener. Everything
// else here is self-contained. Shared helpers/appState come from
// helpers.js/state.js.

let selectedCarId = null;

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
  const imgSrc = car.photo_path ? photoSrc(car.photo_path, car.photo_url) : defImg;
  const imgAlt = car.photo_path ? `${car.reporting_marks} ${car.car_number}` : car.car_type;
  return `
    <div class="car-card${needsMove ? ' car-needs-move' : ''}" data-id="${car.id}">
      <div class="car-thumb">
        ${imgSrc
          ? `<img src="${imgSrc}" alt="${imgAlt}" loading="lazy" width="200" height="130" class="car-thumb-img" />`
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
      ? `<div class="session-car-thumb"><img src="${img}" alt="${c.car_type}" /></div>`
      : `<div class="session-car-thumb no-photo-thumb">${c.car_type}</div>`;
  }
  function powerChip(c, label) {
    const removeBtn = editable
      ? `<button type="button" class="power-chip-remove" data-remove-id="${c.id}" data-remove-type="${label}" title="Remove">✕</button>`
      : "";
    const roleLabel = label === "caboose" ? "Caboose" : "Locomotive";
    return `<div class="power-chip" title="${label}">
      ${powerThumb(c)}
      <div class="session-car-info">
        <span class="session-car-marks">${c.reporting_marks || "—"} ${c.car_number || ""}</span>
        <span class="session-car-move">${roleLabel}</span>
      </div>
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

  checkOrphanedCars();
}

// Delegated once on the stable container elements rather than re-attaching a
// listener per card on every renderCarGrid() call — a full-roster rebuild
// after a single-car edit used to mean hundreds of fresh listeners each time.
function _onCarCardClick(e) {
  const card = e.target.closest(".car-card");
  if (card) openCarDetail(parseInt(card.dataset.id));
}
$("#car-grid").addEventListener("click", _onCarCardClick);
$("#power-pool-list").addEventListener("click", _onCarCardClick);

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

  const hasDataplate = [
    car.light_weight, car.load_limit, car.capacity, car.built_date,
    car.reweigh_date, car.reweigh_location, car.cots_date, car.cots_location,
  ].some(v => v !== null && v !== undefined && v !== "");
  const fmtLbs = (v) => v != null ? `${v.toLocaleString()} lbs` : "—";
  const dataplateHtml = `
    <details class="dataplate-fields"${hasDataplate ? " open" : ""}>
      <summary>Stenciled data</summary>
      <div class="grid">
        <p><strong>Light Weight:</strong> ${fmtLbs(car.light_weight)}</p>
        <p><strong>Load Limit:</strong> ${fmtLbs(car.load_limit)}</p>
      </div>
      <div class="grid">
        <p><strong>Capacity:</strong> ${fmtLbs(car.capacity)}</p>
        <p><strong>Built:</strong> ${car.built_date || "—"}</p>
      </div>
      <div class="grid">
        <p><strong>Reweigh:</strong> ${car.reweigh_date || "—"}${car.reweigh_location ? ` (${car.reweigh_location})` : ""}</p>
        <p><strong>COTS:</strong> ${car.cots_date || "—"}${car.cots_location ? ` (${car.cots_location})` : ""}</p>
      </div>
    </details>`;

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
    ${dataplateHtml}
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
  $("#edit-field-light-weight").value = car.light_weight ?? "";
  $("#edit-field-load-limit").value = car.load_limit ?? "";
  $("#edit-field-capacity").value = car.capacity ?? "";
  $("#edit-field-built-date").value = car.built_date || "";
  $("#edit-field-reweigh-date").value = car.reweigh_date || "";
  $("#edit-field-reweigh-location").value = car.reweigh_location || "";
  $("#edit-field-cots-date").value = car.cots_date || "";
  $("#edit-field-cots-location").value = car.cots_location || "";
  $("#edit-dataplate-details").open = [
    car.light_weight, car.load_limit, car.capacity, car.built_date,
    car.reweigh_date, car.reweigh_location, car.cots_date, car.cots_location,
  ].some(v => v !== null && v !== undefined && v !== "");
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
        ...readDataplateFields("edit-field-"),
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
        <select id="waybill-slot-${i}" data-slot="${i}" class="slot-picker"></select>
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
