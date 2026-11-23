// SPDX-FileCopyrightText: 2026 David Dalzell
// SPDX-License-Identifier: MIT

// Waybill pool (Waybills tab): list, add/edit/delete, Generate waybills
// dialog, and pool-level Auto-assign. Loaded as a classic script before
// app.js. loadWaybillPool is called from app.js's tab-navigation handler;
// buildTrackOptgroups is also called from layout.js and operations.js.
// Everything else here is self-contained. Shared helpers/appState come
// from helpers.js/state.js.

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
// Also called from layout.js and operations.js.
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

let editingWaybillId = null;

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
