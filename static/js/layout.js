// SPDX-FileCopyrightText: 2026 David Dalzell
// SPDX-License-Identifier: MIT

// Layout Setup tab: the location/track/industry tree (render, CRUD, move/
// kebab-menu), the industry create/edit form, car-type admin list, and the
// commodity-map autocomplete + Commodity -> Car Type admin list. Loaded as a
// classic script before app.js. buildTrackOptgroups (Waybill pool, app.js)
// and openPhotoLibrary/renderCarGrid (Roster, app.js) are called from inside
// functions here, never at parse time, so load order relative to app.js is
// safe. Shared helpers/appState come from helpers.js/state.js.

// ── Layout setup ──────────────────────────────────────────────────────────────
async function loadLayout() {
  [[appState.locations, appState.industries, commodityMap, appState.carTypes, appState.switchingAreas], appState.settings] = await Promise.all([
    Promise.all([
      api("GET", "/api/tracks"),
      api("GET", "/api/industries"),
      api("GET", "/api/commodity-car-type-map"),
      api("GET", "/api/car-types"),
      api("GET", "/api/locations"),
    ]),
    api("GET", "/api/settings"),
  ]);
  renderLocationTree();
  renderIndustryList();
  populateIndustryLocationSelect();
  renderCommodityMapList();
  populateCarTypeSelects();
  renderCarTypeList();
  if (appState.settings) {
    $("#clock-start-time").value = appState.settings.clock_start_time;
    $("#clock-speed").value = String(appState.settings.clock_speed);
    appState.opsMode = appState.settings.ops_mode || "free";
    $("#setting-ops-mode").value = appState.opsMode;
  }
}

function populateCarTypeSelect(sel, includeAny) {
  const prev = sel.value;
  const names = appState.carTypes.map(ct => ct.name);
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
  if (addMode !== "manual" || appState.photoPath) {
    hide($("#default-image-offer"));
    return;
  }
  const typeName = $("#field-type").value;
  const ct = appState.carTypes.find(t => t.name === typeName);
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
  const ct = appState.carTypes.find(t => t.name === typeName);
  if (!ct?.default_photo_path) return;
  appState.photoPath = ct.default_photo_path;
  $("#preview-img").src = `/${appState.photoPath}`;
  show($("#upload-preview"));
  hide($("#upload-zone"));
  hide($("#default-image-offer"));
});

$("#btn-dismiss-default-offer").addEventListener("click", () => {
  hide($("#default-image-offer"));
});

function renderCarTypeList() {
  const list = $("#car-type-list");
  if (!appState.carTypes.length) {
    list.innerHTML = '<p class="muted small">No car types defined.</p>';
    return;
  }
  list.innerHTML = appState.carTypes.map(ct => {
    const thumb = ct.default_photo_path
      ? `<img src="/${ct.default_photo_path}" class="car-type-thumb" />`
      : `<div class="car-type-thumb no-photo" style="font-size:0.55rem;">none</div>`;
    return `
    <div class="layout-item">
      ${thumb}
      <span style="flex:1">${ct.name}</span>
      <button class="outline small set-car-type-img" data-id="${ct.id}">Set image</button>
      ${ct.default_photo_path ? `<button class="outline small secondary clear-car-type-img" data-id="${ct.id}">Clear</button>` : ""}
      <button class="icon-btn del-car-type" data-id="${ct.id}" data-name="${ct.name}">🗑</button>
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
  appState.settings = await api("PUT", "/api/settings", {
    clock_start_time: $("#clock-start-time").value,
    clock_speed: parseInt($("#clock-speed").value),
    ops_mode: appState.settings?.ops_mode || "free",
  });
  showToast("Clock settings saved.", "success");
});

$("#ops-mode-form").addEventListener("submit", async e => {
  e.preventDefault();
  const newMode = $("#setting-ops-mode").value;
  appState.settings = await api("PUT", "/api/settings", {
    clock_start_time: appState.settings?.clock_start_time || "08:00",
    clock_speed: appState.settings?.clock_speed || 4,
    ops_mode: newMode,
  });
  appState.opsMode = newMode;
  showToast("Operations mode saved.", "success");
});

// ── Location Tree ────────────────────────────────────────────────────────────

const TREE_COLLAPSE_KEY = "waypoint_tree_collapsed";

function getTreeCollapseState() {
  try {
    return JSON.parse(localStorage.getItem(TREE_COLLAPSE_KEY) || "{}");
  } catch {
    return {};
  }
}

function setTreeCollapsed(key, collapsed) {
  const state = getTreeCollapseState();
  if (collapsed) state[key] = true;
  else delete state[key];
  localStorage.setItem(TREE_COLLAPSE_KEY, JSON.stringify(state));
}

function openCascadeDeleteDialog(title, desc, onConfirm) {
  $("#cascade-delete-title").textContent = title;
  $("#cascade-delete-desc").textContent = desc;
  const confirmBtn = $("#btn-cascade-delete-confirm");
  const freshBtn = confirmBtn.cloneNode(true);
  confirmBtn.replaceWith(freshBtn);
  freshBtn.addEventListener("click", async () => {
    try {
      await onConfirm();
      $("#cascade-delete-dialog").close();
    } catch (err) {
      showToast("Error: " + err.message, "error");
    }
  });
  $("#cascade-delete-dialog").showModal();
}
["#btn-cascade-delete-cancel", "#btn-close-cascade-delete"].forEach(sel =>
  $(sel).addEventListener("click", () => $("#cascade-delete-dialog").close())
);

function makeInlineRenameHandler(nameEl, onSave) {
  nameEl.addEventListener("click", () => {
    const current = nameEl.textContent;
    const input = document.createElement("input");
    input.type = "text";
    input.value = current;
    input.className = "inline-rename-input";
    nameEl.replaceWith(input);
    input.focus();
    input.select();
    let done = false;
    const finish = async (save) => {
      if (done) return;
      done = true;
      const newVal = input.value.trim();
      if (save && newVal && newVal !== current) {
        try {
          await onSave(newVal);
        } catch (err) {
          showToast("Error: " + err.message, "error");
        }
      }
      await loadLayout();
    };
    input.addEventListener("blur", () => finish(true));
    input.addEventListener("keydown", e => {
      if (e.key === "Enter") { e.preventDefault(); finish(true); }
      if (e.key === "Escape") { e.preventDefault(); finish(false); }
    });
  });
}

function renderLocationTree() {
  const root = $("#location-tree");
  if (!root) return;
  const collapsed = getTreeCollapseState();

  const posSort = (a, b) => (a.position ?? a.id) - (b.position ?? b.id);

  const trackRow = (t, isFirst, isLast) => {
    const inds = appState.industries.filter(i => i.location_id === t.id).sort(posSort);
    const type = t.location_type || "yard";
    const tkey = `track-${t.id}`;
    const tCollapsed = !!collapsed[tkey];
    const indRows = inds.length
      ? inds.map((i, j) => `
        <div class="tree-industry-row" data-ind-id="${i.id}">
          <span class="ind-bullet">•</span>
          <span class="ind-name">${i.name}</span>
          <span class="tree-actions">
            <button class="icon-btn move-ind" data-id="${i.id}" data-dir="up" title="Move up"${j === 0 ? " disabled" : ""}>↑</button>
            <button class="icon-btn move-ind" data-id="${i.id}" data-dir="down" title="Move down"${j === inds.length - 1 ? " disabled" : ""}>↓</button>
            <button class="icon-btn tree-kebab-btn" title="More actions" aria-label="More actions">⋮</button>
            <span class="tree-overflow-menu">
              <button class="icon-btn edit-ind-tree" data-id="${i.id}" title="Edit">✏️<span class="kebab-label">Edit</span></button>
              <button class="icon-btn del-ind-tree" data-id="${i.id}" title="Delete">🗑<span class="kebab-label">Delete</span></button>
            </span>
          </span>
        </div>`).join("")
      : `<div class="tree-industry-empty"><em>No industries on this track</em></div>`;
    return `
      <div class="tree-track" data-track-id="${t.id}">
        <div class="tree-track-row">
          <button class="icon-btn caret track-caret" data-tkey="${tkey}" aria-label="Toggle">${tCollapsed ? "▶" : "▼"}</button>
          <span class="tree-track-name" data-id="${t.id}">${t.name}</span>
          <span class="track-type-badge track-type-${type}">${type}</span>
          <span class="tree-actions">
            <button class="icon-btn move-track" data-id="${t.id}" data-dir="up" title="Move up"${isFirst ? " disabled" : ""}>↑</button>
            <button class="icon-btn move-track" data-id="${t.id}" data-dir="down" title="Move down"${isLast ? " disabled" : ""}>↓</button>
            <button class="icon-btn tree-kebab-btn" title="More actions" aria-label="More actions">⋮</button>
            <span class="tree-overflow-menu">
              <button class="btn-muted add-industry-to-track" data-id="${t.id}">+ Industry</button>
              <button class="icon-btn edit-track" data-id="${t.id}" title="Edit">✏️<span class="kebab-label">Edit</span></button>
              <button class="icon-btn del-track" data-id="${t.id}" title="Delete">🗑<span class="kebab-label">Delete</span></button>
            </span>
          </span>
        </div>
        <div class="tree-industries ${tCollapsed ? "hidden" : ""}" data-tkey="${tkey}">${indRows}</div>
      </div>`;
  };

  const groupBlock = (group, isFirst, isLast) => {
    const tracks = (group ? appState.locations.filter(l => l.location_id === group.id) : appState.locations.filter(l => !l.location_id)).sort(posSort);
    const key = group ? `group-${group.id}` : "ungrouped";
    const isCollapsed = !!collapsed[key];
    const count = group ? (group.current_car_count ?? 0) : null;
    const cap = group ? (group.car_capacity ?? null) : null;
    const full = group && cap != null && count >= cap;
    return `
      <div class="tree-group" data-group-key="${key}">
        <div class="tree-group-row">
          <button class="icon-btn caret group-caret" data-key="${key}" aria-label="Toggle">${isCollapsed ? "▶" : "▼"}</button>
          ${group
            ? `<span class="tree-group-name" data-id="${group.id}">${group.name}</span>
               <span class="car-count-pill${full ? " full" : ""}">${count}${cap != null ? " / " + cap : ""} cars</span>`
            : `<span class="tree-group-name muted"><em>Ungrouped tracks</em></span>`}
          <span class="tree-actions">
            ${group ? `
              <button class="icon-btn move-group" data-id="${group.id}" data-dir="up" title="Move up"${isFirst ? " disabled" : ""}>↑</button>
              <button class="icon-btn move-group" data-id="${group.id}" data-dir="down" title="Move down"${isLast ? " disabled" : ""}>↓</button>` : ""}
            <button class="icon-btn tree-kebab-btn" title="More actions" aria-label="More actions">⋮</button>
            <span class="tree-overflow-menu">
              <button class="btn-accent add-track-to-group" data-group-id="${group ? group.id : ""}">+ Track</button>
              ${group ? `
                <button class="icon-btn edit-group" data-id="${group.id}" title="Edit">✏️<span class="kebab-label">Edit</span></button>
                <button class="icon-btn del-group" data-id="${group.id}" title="Delete">🗑<span class="kebab-label">Delete</span></button>` : ""}
            </span>
          </span>
        </div>
        <div class="tree-group-body ${isCollapsed ? "hidden" : ""}" data-key="${key}">
          ${tracks.length ? tracks.map((t, i) => trackRow(t, i === 0, i === tracks.length - 1)).join("") : '<p class="muted small tree-empty">No tracks yet.</p>'}
        </div>
      </div>`;
  };

  const sortedAreas = appState.switchingAreas.slice().sort(posSort);
  const ungroupedTracks = appState.locations.filter(l => !l.location_id);
  root.innerHTML = sortedAreas.map((group, i) => groupBlock(group, i === 0, i === sortedAreas.length - 1)).join("") +
    (ungroupedTracks.length ? groupBlock(null) : "");

  if (!appState.switchingAreas.length && !ungroupedTracks.length) {
    root.innerHTML = emptyState("📍", "No locations yet — add a location with the + Location button.");
    return;
  }

  // Location collapse
  root.querySelectorAll(".group-caret").forEach(btn => {
    btn.addEventListener("click", () => {
      const key = btn.dataset.key;
      const body = root.querySelector(`.tree-group-body[data-key="${key}"]`);
      const nowCollapsed = !body.classList.contains("hidden");
      body.classList.toggle("hidden", nowCollapsed);
      btn.textContent = nowCollapsed ? "▶" : "▼";
      setTreeCollapsed(key, nowCollapsed);
    });
  });

  // Track collapse
  root.querySelectorAll(".track-caret").forEach(btn => {
    btn.addEventListener("click", () => {
      const tkey = btn.dataset.tkey;
      const body = root.querySelector(`.tree-industries[data-tkey="${tkey}"]`);
      const nowCollapsed = !body.classList.contains("hidden");
      body.classList.toggle("hidden", nowCollapsed);
      btn.textContent = nowCollapsed ? "▶" : "▼";
      setTreeCollapsed(tkey, nowCollapsed);
    });
  });

  // Mobile overflow menu (kebab) — Add/Edit/Delete fold behind it under 600px;
  // move up/down arrows stay inline since reordering is the primary action.
  root.querySelectorAll(".tree-kebab-btn").forEach(btn => {
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      const actions = btn.closest(".tree-actions");
      const wasOpen = actions.classList.contains("menu-open");
      root.querySelectorAll(".tree-actions.menu-open").forEach(el => el.classList.remove("menu-open"));
      if (!wasOpen) actions.classList.add("menu-open");
    });
  });
  root.querySelectorAll(".tree-overflow-menu button").forEach(btn => {
    btn.addEventListener("click", () => btn.closest(".tree-actions")?.classList.remove("menu-open"));
  });

  // Add industry to a track (opens the industry form pre-filled)
  root.querySelectorAll(".add-industry-to-track").forEach(btn => {
    btn.addEventListener("click", () => openIndustryForm(parseInt(btn.dataset.id)));
  });

  // Edit industry from the tree
  root.querySelectorAll(".edit-ind-tree").forEach(btn => {
    btn.addEventListener("click", () => {
      const ind = appState.industries.find(i => i.id === parseInt(btn.dataset.id));
      if (ind) openIndustryEdit(ind);
    });
  });

  // Delete industry from the tree
  root.querySelectorAll(".del-ind-tree").forEach(btn => {
    btn.addEventListener("click", () => {
      const ind = appState.industries.find(i => i.id === parseInt(btn.dataset.id));
      if (!ind) return;
      openCascadeDeleteDialog(
        `Delete "${ind.name}"?`,
        "Waybills that reference this industry are also removed or unassigned.",
        () => api("DELETE", `/api/industries/${ind.id}`).then(loadLayout)
      );
    });
  });

  // Reorder locations / tracks / industries (up/down)
  root.querySelectorAll(".move-group").forEach(btn => {
    btn.addEventListener("click", () => {
      api("POST", `/api/locations/${btn.dataset.id}/move`, { direction: btn.dataset.dir })
        .then(loadLayout)
        .catch(err => showToast("Error: " + err.message, "error"));
    });
  });
  root.querySelectorAll(".move-track").forEach(btn => {
    btn.addEventListener("click", () => {
      api("POST", `/api/tracks/${btn.dataset.id}/move`, { direction: btn.dataset.dir })
        .then(loadLayout)
        .catch(err => showToast("Error: " + err.message, "error"));
    });
  });
  root.querySelectorAll(".move-ind").forEach(btn => {
    btn.addEventListener("click", () => {
      api("POST", `/api/industries/${btn.dataset.id}/move`, { direction: btn.dataset.dir })
        .then(loadLayout)
        .catch(err => showToast("Error: " + err.message, "error"));
    });
  });

  // Add track to group
  root.querySelectorAll(".add-track-to-group").forEach(btn => {
    btn.addEventListener("click", () => {
      $("#tf-name").value = "";
      $("#tf-type").value = "yard";
      $("#tf-capacity").value = "";
      $("#tf-group-id").value = btn.dataset.groupId || "";
      $("#tf-edit-id").value = "";
      showOnlyLayoutForm($("#track-form"));
    });
  });

  // Edit group
  root.querySelectorAll(".edit-group").forEach(btn => {
    btn.addEventListener("click", () => {
      const group = appState.switchingAreas.find(a => a.id === parseInt(btn.dataset.id));
      if (!group) return;
      $("#lg-name").value = group.name;
      $("#lg-capacity").value = group.car_capacity ?? "";
      $("#lg-edit-id").value = group.id;
      showOnlyLayoutForm($("#lg-form"));
    });
  });

  // Delete group (cascade warning)
  root.querySelectorAll(".del-group").forEach(btn => {
    btn.addEventListener("click", () => {
      const group = appState.switchingAreas.find(a => a.id === parseInt(btn.dataset.id));
      if (!group) return;
      const tracks = appState.locations.filter(l => l.location_id === group.id);
      openCascadeDeleteDialog(
        `Delete "${group.name}"?`,
        tracks.length
          ? `${tracks.length} track${tracks.length === 1 ? "" : "s"} will become ungrouped — they are not deleted.`
          : "This cannot be undone.",
        () => api("DELETE", `/api/locations/${group.id}`).then(loadLayout)
      );
    });
  });

  // Edit track
  root.querySelectorAll(".edit-track").forEach(btn => {
    btn.addEventListener("click", () => {
      const t = appState.locations.find(l => l.id === parseInt(btn.dataset.id));
      if (!t) return;
      $("#tf-name").value = t.name;
      $("#tf-type").value = t.location_type;
      $("#tf-capacity").value = t.car_capacity ?? "";
      $("#tf-group-id").value = t.location_id || "";
      $("#tf-edit-id").value = t.id;
      showOnlyLayoutForm($("#track-form"));
    });
  });

  // Delete track (cascade warning, with staging-merge / blocking-cars special cases)
  root.querySelectorAll(".del-track").forEach(btn => {
    btn.addEventListener("click", () => {
      const locId = parseInt(btn.dataset.id);
      const loc = appState.locations.find(l => l.id === locId);
      if (!loc) return;
      if (loc.location_type === "staging") {
        openStagingMergeDialog(loc);
        return;
      }
      const blocking = appState.cars.filter(c => c.current_location_id === locId);
      if (blocking.length) {
        openLocationBlockDialog(loc, blocking);
        return;
      }
      const indCount = appState.industries.filter(i => i.location_id === locId).length;
      openCascadeDeleteDialog(
        `Delete "${loc.name}"?`,
        indCount ? `This will also remove ${indCount} industr${indCount === 1 ? "y" : "ies"}.` : "This cannot be undone.",
        () => api("DELETE", `/api/tracks/${locId}`).then(loadLayout)
      );
    });
  });

  // Inline rename — group names (PUT /api/locations is a full replace)
  root.querySelectorAll(".tree-group-name").forEach(nameEl => {
    makeInlineRenameHandler(nameEl, (newVal) => {
      const group = appState.switchingAreas.find(a => a.id === parseInt(nameEl.dataset.id));
      return api("PUT", `/api/locations/${nameEl.dataset.id}`, {
        name: newVal,
        car_capacity: group?.car_capacity ?? 10,
      });
    });
  });

  // Inline rename — track names (PUT /api/tracks is a full replace)
  root.querySelectorAll(".tree-track-name").forEach(nameEl => {
    makeInlineRenameHandler(nameEl, (newVal) => {
      const track = appState.locations.find(l => l.id === parseInt(nameEl.dataset.id));
      return api("PUT", `/api/tracks/${nameEl.dataset.id}`, {
        name: newVal,
        location_type: track?.location_type || "yard",
        location_id: track?.location_id || null,
        car_capacity: track?.car_capacity ?? null,
      });
    });
  });
}

function openStagingMergeDialog(loc) {
  const otherStaging = appState.locations.filter(l => l.location_type === "staging" && l.id !== loc.id);
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
    await api("DELETE", `/api/tracks/${stagingMergeDeleteId}?merge_into_id=${mergeInto}`);
    $("#staging-merge-dialog").close();
    showToast("Staging location merged and deleted.", "success");
    await loadLayout();
    appState.cars = await api("GET", "/api/cars");
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
  if (!appState.industries.length) {
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

  list.innerHTML = appState.industries.map(i => {
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
            <button class="icon-btn edit-ind" data-id="${i.id}">✏️</button>
            <button class="icon-btn del-ind" data-id="${i.id}">🗑</button>
          </span>
        </div>
        ${unmappedChipsHtml(i.commodities, "inbound", i.id)}
        ${unmappedChipsHtml(i.outbound_commodities, "outbound", i.id)}
      </div>`;
  }).join("");

  $$(".edit-ind").forEach(btn => {
    btn.addEventListener("click", () => {
      const ind = appState.industries.find(i => i.id === parseInt(btn.dataset.id));
      if (ind) openIndustryEdit(ind);
    });
  });

  $$(".del-ind").forEach(btn => {
    btn.addEventListener("click", () => {
      const ind = appState.industries.find(i => i.id === parseInt(btn.dataset.id));
      if (!ind) return;
      openCascadeDeleteDialog(
        `Delete "${ind.name}"?`,
        "Waybills that reference this industry are also removed or unassigned.",
        () => api("DELETE", `/api/industries/${ind.id}`).then(loadLayout)
      );
    });
  });

  // Inline unmapped chip handlers
  list.addEventListener("click", async e => {
    const indId = parseInt(e.target.closest("[data-ind-id]")?.dataset.indId);
    const ind = appState.industries.find(i => i.id === indId);
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
  if (!appState.carTypes.length) {
    el.innerHTML = '<span class="muted" style="font-size:0.8rem">No car types defined</span>';
    return;
  }
  el.innerHTML = appState.carTypes.map(ct => {
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
    return `<label class="ct-pill"><input type="checkbox" id="spot-${n}" value="${n}"${checked}><span>${n}</span></label>`;
  }).join("");
}

function getSpotPickerValues(el) {
  return Array.from(el.querySelectorAll('input[type="checkbox"]:checked')).map(cb => cb.value).join(", ");
}

function populateIndustryLocationSelect() {
  $("#ind-location").innerHTML = buildTrackOptgroups('<option value="">— no track —</option>');
}

function refreshSpotPickerForLocation(selectedStr = "") {
  const locId = parseInt($("#ind-location").value);
  const loc = appState.locations.find(l => l.id === locId);
  populateSpotPicker($("#ind-spot-numbers"), loc?.car_capacity ?? 0, selectedStr);
}

$("#ind-location").addEventListener("change", () => refreshSpotPickerForLocation());

// Location group form handlers
$("#btn-add-location-group").addEventListener("click", () => {
  $("#lg-name").value = "";
  $("#lg-capacity").value = "";
  $("#lg-edit-id").value = "";
  showOnlyLayoutForm($("#lg-form"));
});
$("#btn-cancel-lg").addEventListener("click", () => hide($("#lg-form")));
$("#lg-form").addEventListener("submit", async e => {
  e.preventDefault();
  const editId = $("#lg-edit-id").value;
  const body = {
    name: $("#lg-name").value.trim(),
    car_capacity: $("#lg-capacity").value ? parseInt($("#lg-capacity").value) : null,
  };
  try {
    if (editId) {
      await api("PUT", `/api/locations/${editId}`, body);
    } else {
      await api("POST", "/api/locations", body);
    }
    hide($("#lg-form"));
    await loadLayout();
  } catch (err) {
    showToast("Error: " + err.message, "error");
  }
});

// Track form handlers
$("#btn-cancel-track-form").addEventListener("click", () => hide($("#track-form")));
$("#track-form").addEventListener("submit", async e => {
  e.preventDefault();
  const editId = $("#tf-edit-id").value;
  const groupId = $("#tf-group-id").value;
  const body = {
    name: $("#tf-name").value.trim(),
    location_type: $("#tf-type").value,
    location_id: groupId ? parseInt(groupId) : null,
    car_capacity: $("#tf-capacity").value ? parseInt($("#tf-capacity").value) : null,
  };
  try {
    if (editId) {
      await api("PUT", `/api/tracks/${editId}`, body);
    } else {
      await api("POST", "/api/tracks", body);
    }
    hide($("#track-form"));
    await loadLayout();
  } catch (err) {
    showToast("Error: " + err.message, "error");
  }
});

// Open the industry form for a new industry, optionally pre-attached to a track.
function openIndustryForm(trackId = null) {
  $("#ind-name").value = "";
  populateCarTypeMultiSelect($("#ind-inbound-car-types"), "");
  $("#ind-inbound-commodities").value = "";
  populateCarTypeMultiSelect($("#ind-outbound-car-types"), "");
  $("#ind-outbound-commodities").value = "";
  $("#ind-edit-id").value = "";
  roleToCheckboxes("consumer");
  hide($("#inbound-commodity-warn"));
  hide($("#outbound-commodity-warn"));
  if (trackId) {
    $("#ind-location").value = String(trackId);
    refreshSpotPickerForLocation("");
  } else {
    $("#ind-location").value = "";
    populateSpotPicker($("#ind-spot-numbers"), 0, "");
  }
  showOnlyLayoutForm($("#industry-form"));
  $("#industry-form").scrollIntoView({ behavior: "smooth", block: "center" });
}

// Open the industry form to edit an existing industry.
function openIndustryEdit(ind) {
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
  showOnlyLayoutForm($("#industry-form"));
  $("#industry-form").scrollIntoView({ behavior: "smooth", block: "center" });
}

$("#btn-add-industry").addEventListener("click", () => openIndustryForm());
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
        <button class="icon-btn edit-cmap" data-id="${m.id}">✏️</button>
        <button class="icon-btn del-cmap" data-id="${m.id}">🗑</button>
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
