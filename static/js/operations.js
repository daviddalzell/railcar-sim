// SPDX-FileCopyrightText: 2026 David Dalzell
// SPDX-License-Identifier: MIT

// Operations tab: the quick-op plan preview, the full active-session
// lifecycle (spotting conflicts, car marking, end-of-session), the
// always-visible Layout Status strip, and the Virtual Dispatcher (consist
// building/management). These four areas call into each other constantly
// (loadOperations -> Session/Dispatcher/Clock, Dispatcher's wireConsistCard
// -> Session's saveSession/renderActiveSession/collapseDispatcher, etc.), so
// they're kept in one file rather than forced into separate modules with an
// artificial import boundary. Loaded as a classic script before app.js.
// renderCarGrid/defaultCarImage/renderPowerStrip (Roster) and
// buildTrackOptgroups (Waybill pool) remain in app.js and are called from
// inside functions here, never at parse time, so load order is safe.
// Shared helpers/appState come from helpers.js/state.js; fetchAndStartClock/
// startClockTick/stopClock come from clock.js.

// ── Operations view ───────────────────────────────────────────────────────────
async function loadOperations() {
  loadSessionFromStorage();

  // Layout Status strip — always visible
  await renderLayoutStatus();

  // Dispatcher always visible
  if (!appState.locations.length || !appState.switchingAreas.length) {
    [appState.locations, appState.switchingAreas] = await Promise.all([
      api("GET", "/api/tracks"),
      api("GET", "/api/locations"),
    ]);
  }
  if (!appState.settings) {
    appState.settings = await api("GET", "/api/settings");
    appState.opsMode = appState.settings?.ops_mode || "free";
  }
  await loadDispatcherPanel();
  show($("#dispatcher-panel"));

  fetchAndStartClock();

  if (appState.session) {
    $("#ops-header-buttons").innerHTML = ""; // cleared by renderActiveSession
    renderActiveSession();
    return;
  }

  $("#ops-title").textContent = "Quick Op Session";
  // Idle state: "Generate Switch List" shows pre-review before committing
  $("#ops-header-buttons").innerHTML =
    `<button id="btn-plan-session">Generate Switch List</button>`;
  document.getElementById("btn-plan-session").addEventListener("click", async () => {
    const btn = document.getElementById("btn-plan-session");
    await withLoading(btn, "Planning…", async () => {
      try {
        const plan = await api("POST", "/api/session/plan");
        track("switch_list_generated", {
          car_count: (plan.arrivals?.length || 0) + (plan.departures?.length || 0) + (plan.spots?.length || 0),
        });
        renderPlanPreview(plan);
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

function _startSessionFromPlan(plan) {
  appState.session = {
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
        isPriority: c.active_waybill?.is_priority || false,
        priority: Math.floor(Math.random() * 1000),
        group: "arrivals",
        status: "pending",
        conflictDecision: null,
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
        isPriority: c.active_waybill?.is_priority || false,
        priority: Math.floor(Math.random() * 1000),
        group: "spots",
        status: "pending",
        conflictDecision: null,
      })),
    ],
  };
  track("session_started", { source: "quick_op", car_count: appState.session.cars.length });
  saveSession();
  renderActiveSession();
  collapseDispatcher();
  setTimeout(() => document.getElementById("ops-header")?.scrollIntoView({ behavior: "smooth" }), 50);
}

function renderPlanPreview(plan) {
  const list = $("#ops-list");
  const groups = [
    { label: "Set out from staging", cars: plan.arrivals || [],   empty: "No setouts planned." },
    { label: "Cars to spot",         cars: plan.spots || [],       empty: "No local spots planned." },
    { label: "Pick up for staging",  cars: plan.departures || [],  empty: "No pickups planned." },
  ];
  const warningHtml = (plan.warnings || []).map(w =>
    `<li style="color:var(--pico-del-color,#c0392b)">${w}</li>`
  ).join("");
  const total = (plan.arrivals?.length || 0) + (plan.departures?.length || 0) + (plan.spots?.length || 0);

  list.innerHTML = `
    <div style="display:flex;gap:0.5rem;margin-bottom:1rem;flex-wrap:wrap">
      <button id="btn-confirm-preview" class="contrast">&#9654; Start session (${total} moves)</button>
      <button id="btn-regenerate-preview" class="outline">&#8635; Regenerate</button>
    </div>
    ${warningHtml ? `<ul style="margin-bottom:1rem">${warningHtml}</ul>` : ""}
    ${groups.map(g => `
      <details open>
        <summary style="font-weight:600;margin-bottom:0.5rem">${g.label} (${g.cars.length})</summary>
        ${g.cars.length === 0
          ? `<p style="color:var(--pico-muted-color)">${g.empty}</p>`
          : g.cars.map(c => `
            <div style="display:flex;gap:0.5rem;align-items:center;
                        padding:0.4rem 0;border-bottom:1px solid var(--pico-table-border-color)">
              ${c.photo_url || c.photo_path
                ? `<img src="${photoSrc(c.photo_path, c.photo_url)}"
                       style="width:48px;height:32px;object-fit:cover;border-radius:4px" alt="">`
                : `<div style="width:48px;height:32px;background:var(--pico-secondary-background);
                              border-radius:4px;flex-shrink:0"></div>`}
              <div>
                <strong>${c.reporting_marks || "—"} ${c.car_number || ""}</strong>
                <span style="color:var(--pico-muted-color);font-size:0.85em"> &middot; ${c.car_type || "?"}</span>
                ${c.active_waybill?.is_priority ? `<span style="background:var(--pico-primary-background,#1a56a4);color:#fff;font-size:0.7em;padding:1px 5px;border-radius:3px;margin-left:4px">Priority</span>` : ""}<br>
                <span style="font-size:0.85em">
                  ${c.session_from_location_name || "?"} &rarr; ${c.session_to_location_name || "?"}
                </span>
              </div>
            </div>`).join("")}
      </details>`).join("")}
  `;

  document.getElementById("btn-confirm-preview").addEventListener("click", () => _startSessionFromPlan(plan));
  document.getElementById("btn-regenerate-preview").addEventListener("click", async () => {
    const btn = document.getElementById("btn-regenerate-preview");
    await withLoading(btn, "Regenerating…", async () => {
      renderPlanPreview(await api("POST", "/api/session/plan"));
    });
  });
}

// ── Operating Session ─────────────────────────────────────────────────────────
// session = { cars: [{id, marks, carType, fromLocation, toLocation, status}], warnings: [] }
// status: 'pending' | 'done' | 'cp'

function saveSession() {
  localStorage.setItem("railcar-session", appState.session ? JSON.stringify(appState.session) : "");
}

function loadSessionFromStorage() {
  try { appState.session = JSON.parse(localStorage.getItem("railcar-session") || "null"); }
  catch { appState.session = null; }
}

function detectSpottingConflicts() {
  if (!appState.session) return;
  // Clear stale conflictDecision on all cars first; re-seed below for active conflicts
  appState.session.cars.forEach(c => { c.conflictDecision = null; });

  const relevant = appState.session.cars.filter(c =>
    (c.group === "arrivals" || c.group === "spots") && c.toIndustryId && c.status !== "cp"
  );
  const byIndustry = {};
  for (const car of relevant) {
    (byIndustry[car.toIndustryId] = byIndustry[car.toIndustryId] || []).push(car);
  }
  const conflicts = [];
  for (const [indId, incoming] of Object.entries(byIndustry)) {
    const ind = appState.industries.find(i => i.id === parseInt(indId));
    const spotNums = (ind?.spot_numbers || "").split(",").filter(s => s.trim());
    if (!spotNums.length) continue;
    const industryCapacity = spotNums.length;
    const currentCount = appState.cars.filter(c =>
      c.current_location_id === ind.location_id &&
      c.active_waybill?.industry_id === ind.id
    ).length;
    if (currentCount + incoming.length > industryCapacity) {
      const conflict = { ind, capacity: industryCapacity, spotNums, current: currentCount, cars: incoming };
      conflicts.push(conflict);
      // Seed per-car recommendations based on four-tier sort (only if not already decided)
      const available = industryCapacity - currentCount;
      const sorted = [...incoming].sort((a, b) => {
        if (b.isPriority !== a.isPriority) return (b.isPriority ? 1 : 0) - (a.isPriority ? 1 : 0);
        if (b.cpSessions !== a.cpSessions) return b.cpSessions - a.cpSessions;
        const typeA = carTypeMatchesIndustry(a, ind) ? 1 : 0;
        const typeB = carTypeMatchesIndustry(b, ind) ? 1 : 0;
        if (typeB !== typeA) return typeB - typeA;
        return a.priority - b.priority;
      });
      sorted.forEach((car, i) => {
        const sc = appState.session.cars.find(c => c.id === car.id);
        if (sc && sc.conflictDecision == null) {
          sc.conflictDecision = i < available ? "spot" : "hold";
        }
      });
    }
  }
  appState.session.conflicts = conflicts;
}

function carTypeMatchesIndustry(car, ind) {
  if (!ind.inbound_car_types) return false;
  const accepted = ind.inbound_car_types.split(",").map(s => s.trim().toLowerCase());
  return accepted.includes((car.carType || "").toLowerCase());
}

function _commitConflictDecisions(conflict) {
  conflict.cars.forEach(car => {
    const sc = appState.session.cars.find(c => c.id === car.id);
    if (sc && sc.conflictDecision === "hold") sc.status = "cp";
  });
  saveSession();
  detectSpottingConflicts();
  renderSpottingConflicts();
  renderActiveSession();
}

function renderSpottingConflicts() {
  const el = document.getElementById("spotting-conflicts");
  if (!el) return;
  const conflicts = appState.session?.conflicts || [];
  if (!conflicts.length) { el.innerHTML = ""; return; }

  el.innerHTML = `
    <div class="conflict-panel">
      <p class="conflict-panel-title">⚠ Resolve Spotting Conflicts</p>
      ${conflicts.map(({ ind, capacity, spotNums, current, cars: incoming }) => {
        const available = capacity - current;
        const spotCount = incoming.filter(c => {
          const sc = appState.session.cars.find(x => x.id === c.id);
          return sc?.conflictDecision === "spot";
        }).length;
        const spotsLeft = available - spotCount;
        const metaLine = [
          ind.commodities ? `Accepts: ${ind.commodities}` : "",
          ind.inbound_car_types ? `Car types: ${ind.inbound_car_types}` : "",
        ].filter(Boolean).join(" · ");
        return `
        <div class="conflict-group" data-ind-id="${ind.id}">
          <div class="conflict-group-header">
            <div class="conflict-industry-header">
              <div class="conflict-industry-name">${ind.name}</div>
              ${metaLine ? `<div class="conflict-industry-meta">${metaLine}</div>` : ""}
              <div class="conflict-spot-status">${available} spot${available !== 1 ? "s" : ""} open &middot; ${incoming.length} car${incoming.length !== 1 ? "s" : ""} arriving</div>
            </div>
            <button class="outline small conflict-accept-suggestion" data-ind-id="${ind.id}">Accept suggestion</button>
          </div>
          ${incoming.map(car => {
            const sc = appState.session.cars.find(x => x.id === car.id);
            const decision = sc?.conflictDecision || null;
            const isHeld = decision === "hold";
            const isSpot = decision === "spot";
            const spotDisabled = spotsLeft <= 0 && !isSpot;
            return `
            <div class="conflict-car-row${car.isPriority ? " is-priority" : ""}${isHeld ? " is-held" : ""}">
              <div class="conflict-car-identity">
                <span class="conflict-car-marks">${car.marks} <span class="muted">${car.carType}</span></span>
                ${car.isPriority ? `<span class="conflict-priority-label">Perishable &mdash; time-sensitive</span>` : ""}
                ${car.cpSessions > 0 ? `<span class="aging-badge">Held ${car.cpSessions} session${car.cpSessions !== 1 ? "s" : ""}</span>` : ""}
              </div>
              <div class="conflict-car-actions">
                <button class="outline small conflict-spot-btn${isSpot ? " is-active" : ""}"
                        data-car-id="${car.id}" data-ind-id="${ind.id}"
                        ${spotDisabled ? "disabled" : ""}>&#10003; Spot</button>
                <button class="outline small conflict-hold-btn${isHeld ? " is-active" : ""}"
                        data-car-id="${car.id}" data-ind-id="${ind.id}">Hold</button>
              </div>
            </div>`;
          }).join("")}
        </div>`;
      }).join("")}
    </div>`;

  // Spot button handler
  el.querySelectorAll(".conflict-spot-btn").forEach(btn => {
    btn.addEventListener("click", () => {
      const carId = parseInt(btn.dataset.carId);
      const indId = parseInt(btn.dataset.indId);
      const conflict = (appState.session.conflicts || []).find(c => c.ind.id === indId);
      const sc = appState.session.cars.find(c => c.id === carId);
      if (!conflict || !sc) return;
      const available = conflict.capacity - conflict.current;

      if (sc.conflictDecision === "spot") {
        // Toggle off — un-spot this car
        sc.conflictDecision = "hold";
        saveSession();
        renderSpottingConflicts();
        return;
      }
      const spotCount = conflict.cars.filter(c => {
        const x = appState.session.cars.find(s => s.id === c.id);
        return x?.conflictDecision === "spot";
      }).length;
      if (spotCount >= available) return; // defensive guard
      sc.conflictDecision = "spot";
      if (spotCount + 1 >= available) {
        // All spots claimed — auto-commit undecided cars as hold
        conflict.cars.forEach(car => {
          const x = appState.session.cars.find(s => s.id === car.id);
          if (x && x.conflictDecision !== "spot") x.conflictDecision = "hold";
        });
        _commitConflictDecisions(conflict);
      } else {
        saveSession();
        renderSpottingConflicts();
      }
    });
  });

  // Hold button handler
  el.querySelectorAll(".conflict-hold-btn").forEach(btn => {
    btn.addEventListener("click", () => {
      const carId = parseInt(btn.dataset.carId);
      const indId = parseInt(btn.dataset.indId);
      const conflict = (appState.session.conflicts || []).find(c => c.ind.id === indId);
      const sc = appState.session.cars.find(c => c.id === carId);
      if (!conflict || !sc) return;

      if (sc.conflictDecision === "hold" && sc.status === "cp") {
        // Un-hold — restore to pending
        sc.status = "pending";
        sc.conflictDecision = null;
        saveSession();
        detectSpottingConflicts();
        renderSpottingConflicts();
        renderActiveSession();
        return;
      }
      sc.conflictDecision = "hold";
      sc.status = "cp";
      saveSession();
      detectSpottingConflicts();
      renderSpottingConflicts();
      renderActiveSession();
    });
  });

  // Accept suggestion handler — commit all pre-filled decisions
  el.querySelectorAll(".conflict-accept-suggestion").forEach(btn => {
    btn.addEventListener("click", () => {
      const indId = parseInt(btn.dataset.indId);
      const conflict = (appState.session.conflicts || []).find(c => c.ind.id === indId);
      if (!conflict) return;
      _commitConflictDecisions(conflict);
    });
  });
}

function sessionProgress() {
  if (!appState.session) return { total: 0, done: 0, cp: 0, pending: 0 };
  const total   = appState.session.cars.length;
  const done    = appState.session.cars.filter(c => c.status === "done").length;
  const cp      = appState.session.cars.filter(c => c.status === "cp").length;
  const pending = appState.session.cars.filter(c => c.status === "pending").length;
  return { total, done, cp, pending };
}

function markCar(carId, status) {
  const car = appState.session && appState.session.cars.find(c => c.id === carId);
  if (!car) return;
  // toggle: clicking the same status again resets to pending
  car.status = car.status === status ? "pending" : status;
  // Keep conflictDecision in sync so the conflict panel reflects manual overrides
  if (car.status === "cp")      car.conflictDecision = "hold";
  if (car.status === "pending") car.conflictDecision = null;
  saveSession();
  detectSpottingConflicts();
  renderSpottingConflicts();
  renderActiveSession();
}

function updateSessionBar() {
  const bar = document.getElementById("session-status-bar");
  if (!bar) return;
  if (!appState.session) { bar.classList.add("hidden"); return; }
  bar.classList.remove("hidden");
  const { total, done, cp, pending } = sessionProgress();
  const label = appState.session.trainNumber
    ? `Train #${appState.session.trainNumber}`
    : (appState.session.trainName || "Active Session");
  document.getElementById("session-bar-label").textContent = label;
  document.getElementById("session-bar-progress").textContent =
    `${done + cp} / ${total} worked${pending === 0 ? " — ready to end" : ""}`;
}

document.getElementById("session-bar-goto")?.addEventListener("click", () => {
  document.querySelector('[data-tab="operations"]').click();
  setTimeout(() => {
    document.getElementById("ops-header")?.scrollIntoView({ behavior: "smooth" });
  }, 80);
});

function collapseDispatcher() {
  const body = document.getElementById("dispatcher-body");
  const btn  = document.getElementById("btn-toggle-dispatcher");
  if (body && !body.classList.contains("hidden")) {
    body.classList.add("hidden");
    if (btn) btn.textContent = "▶";
  }
}

function restoreDispatcher() {
  const body = document.getElementById("dispatcher-body");
  const btn  = document.getElementById("btn-toggle-dispatcher");
  if (body) {
    body.classList.remove("hidden");
    if (btn) btn.textContent = "▼";
  }
}

function renderActiveSession() {
  detectSpottingConflicts();
  renderSpottingConflicts();

  const titleParts = [];
  if (appState.session.trainNumber) titleParts.push(`Train #${appState.session.trainNumber}`);
  if (appState.session.trainName) titleParts.push(`"${appState.session.trainName}"`);
  $("#ops-title").textContent = titleParts.length ? titleParts.join(" ") : "Active Session";

  const warnEl = $("#session-warnings");
  if (appState.session.warnings?.length) {
    warnEl.innerHTML = appState.session.warnings.map(w => `<p style="margin:0.2rem 0">⚠ ${w}</p>`).join("");
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
    track("session_cancelled");
    const cancelledPlanId = appState.session?.planId;
    appState.session = null;
    saveSession();
    updateSessionBar();
    restoreDispatcher();
    if (cancelledPlanId) {
      try { await api("PATCH", `/api/dispatcher/plan/${cancelledPlanId}/status`, { status: "draft" }); } catch {}
    }
    loadOperations();
  });

  const arrivals   = appState.session.cars.filter(c => c.group === "arrivals");
  const departures = appState.session.cars.filter(c => c.group === "departures");
  const spots      = appState.session.cars.filter(c => c.group === "spots");

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
  const powerHtml = renderPowerStrip(appState.session.power, appState.session.caboose);

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
  updateSessionBar();
}

async function handleEndSession() {
  const cpCars = appState.session.cars.filter(c => c.status === "cp");
  const doneCars = appState.session.cars.filter(c => c.status === "done");

  if (!doneCars.length && !cpCars.length) {
    showToast("No cars have been marked — work some cars first.", "warn");
    return;
  }

  if (cpCars.length) {
    // Show CP resolution dialog
    const locOptions = appState.locations.map(l => `<option value="${l.id}">${l.name} (${l.location_type})</option>`).join("");
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
      track("session_completed", { moves_completed: result.updated.length });
      if (appState.session?.planId) {
        try { await api("PATCH", `/api/dispatcher/plan/${appState.session.planId}/status`, { status: "complete" }); } catch {}
      }
      appState.session = null;
      saveSession();
      updateSessionBar();
      restoreDispatcher();
      result.updated.forEach(updated => {
        const idx = appState.cars.findIndex(c => c.id === updated.id);
        if (idx !== -1) appState.cars[idx] = updated;
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

  function carListHtml(carList) {
    if (!carList.length) return '<p class="muted small" style="margin:0.25rem 0.5rem">No cars here.</p>';
    return carList.map(c =>
      `<div class="layout-item" style="padding:0.2rem 0.5rem;font-size:0.8rem">
         <span><strong>${c.reporting_marks || "—"} ${c.car_number || ""}</strong> <em>${c.car_type}</em></span>
         <span class="muted">${c.destination_name ? "→ " + c.destination_name : "—"}</span>
       </div>`
    ).join("");
  }

  areasEl.innerHTML = status.locations.map(a => {
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
  const yardFilter = l => l.location_type === "staging" || l.location_type === "yard";
  const yardOptions = buildTrackOptgroups('<option value="">— select —</option>', yardFilter);
  originSel.innerHTML = yardOptions;
  destSel.innerHTML = yardOptions;
  areaSel.innerHTML = '<option value="">— select area —</option>' +
    appState.switchingAreas.map(a => `<option value="${a.id}">${a.name} (${a.current_car_count ?? 0}/${a.car_capacity})</option>`).join("");

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

  const instrLabel = { free: "Notes", timetable_train_order: "Train Order", track_warrant: "Track Warrant" }[appState.opsMode] || "Notes";

  const route = plan.origin_name && plan.destination_name
    ? `<div class="muted small consist-route">${plan.origin_name}${plan.location_name ? ` → ${plan.location_name}` : ""} → ${plan.destination_name}</div>`
    : "";

  const assignedElsewhere = new Set(
    dispatchPlans.filter(p => p.id !== plan.id).flatMap(p => (p.power || []).map(c => c.id))
  );
  const caboosesElsewhere = new Set(
    dispatchPlans.filter(p => p.id !== plan.id && p.caboose).map(p => p.caboose.id)
  );
  const locos    = appState.cars.filter(c => c.car_type === "locomotive" && !assignedElsewhere.has(c.id));
  const cabooses = appState.cars.filter(c => c.car_type === "caboose"    && !caboosesElsewhere.has(c.id));
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

  const metaHtml = (crew || route || !hasPower) ? `
    <div class="panel-body" style="padding-bottom:0.4rem">
      ${crew ? `<div class="muted small" style="font-size:0.8rem">${crew}</div>` : ""}
      ${route}
      ${!hasPower ? `<div class="muted small consist-no-power-hint" style="font-size:0.75rem;color:var(--color-warning,#e07b00)">⚠ No locomotive assigned — open to assign power</div>` : ""}
    </div>` : "";

  return `
  <article class="consist-card panel-card" data-plan-id="${plan.id}" style="margin-bottom:0.75rem">
    <div class="panel-head">
      <div class="section-header-title">
        <button class="icon-btn caret consist-toggle" data-plan-id="${plan.id}">▶</button>
        <span class="panel-title">${statusBadge} <strong>${trainTitle}${trainName}</strong>${depTime}</span>
      </div>
      <div class="button-row">
        <button class="consist-start-session" data-plan-id="${plan.id}"${(total === 0 || !hasPower || !!appState.session || plan.status === "complete") ? " disabled" : ""}>Start Session</button>
      </div>
    </div>
    ${metaHtml}
    <div class="consist-body hidden panel-body compact-form" data-plan-id="${plan.id}" style="padding-top:${metaHtml ? "0" : "0.6rem"}">

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
    const powerCars  = powerIds.map(id => appState.cars.find(c => c.id === id)).filter(Boolean);
    const cabooseCar = cabooseId ? appState.cars.find(c => c.id === cabooseId) : null;
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

    if (appState.session) {
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
        isPriority: (group !== "departures") ? (c.active_waybill?.is_priority || false) : false,
        priority: (group !== "departures") ? Math.floor(Math.random() * 1000) : 0,
        group,
        status: "pending",
        conflictDecision: null,
      });

      const firstLoco = (plan.power || [])[0];
      const locoLabel = firstLoco
        ? `${firstLoco.reporting_marks || ""}${firstLoco.car_number ? " " + firstLoco.car_number : ""}`.trim()
        : "";

      appState.session = {
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
      track("session_started", { source: "dispatcher", car_count: appState.session.cars.length });
      saveSession();
      renderActiveSession();
      document.querySelector('[data-tab="operations"]').click();
      collapseDispatcher();
      setTimeout(() => document.getElementById("ops-header")?.scrollIntoView({ behavior: "smooth" }), 120);
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
  if (!originId || !areaId || !destId) { showToast("Select an origin, location, and destination first.", "warning"); return; }
  const btn = $("#btn-build-consist");
  await withLoading(btn, "Building…", async () => {
    try {
      const newPlan = await api("POST", "/api/dispatcher/build-plan", {
        origin_location_id: originId,
        location_id: areaId,
        destination_location_id: destId,
      });
      track("dispatcher_plan_built");
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
