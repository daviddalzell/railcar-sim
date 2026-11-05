// SPDX-FileCopyrightText: 2026 David Dalzell
// SPDX-License-Identifier: MIT

// Fast-clock state + ticking, the clock/ops Server-Sent-Events streams, and
// the always-visible clock-bar controls (pause / reset). Loaded as a classic
// script before app.js. app.js references these at runtime (loadOperations ->
// fetchAndStartClock, session end -> stopClock, dispatcher -> clockState) and
// once synchronously (init() -> _openOpsEventSource), so this must load first.
// _handleOpsEvent calls loadLayout() (app.js) but only on an SSE event
// (runtime). Shared helpers ($, api, _subscriberId) come from helpers.js.

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

// ── Ops notifications SSE ─────────────────────────────────────────────────────
let _opsEventSource = null;

function _openOpsEventSource() {
  if (_opsEventSource) return;
  _opsEventSource = new EventSource(`/api/ops/events?sid=${_subscriberId}`);
  _opsEventSource.onmessage = e => {
    try {
      const evt = JSON.parse(e.data);
      _handleOpsEvent(evt);
    } catch {}
  };
  _opsEventSource.onerror = () => {
    _opsEventSource.close();
    _opsEventSource = null;
    setTimeout(_openOpsEventSource, 5000);
  };
}

function _handleOpsEvent(evt) {
  const { type } = evt;
  if (type === "session_started") {
    showToast(`Session started — ${evt.car_count} car${evt.car_count !== 1 ? "s" : ""} queued`, "success");
  } else if (type === "session_ended") {
    showToast(`Session ended — ${evt.moves_completed} move${evt.moves_completed !== 1 ? "s" : ""} completed`, "success");
    loadLayout();  // keep all devices in sync after car locations change
  } else if (type === "plan_created") {
    const label = evt.train_number || evt.train_name || `Plan #${evt.plan_id}`;
    showToast(`Consist built: ${label} — ${evt.car_count} car${evt.car_count !== 1 ? "s" : ""}`, "info");
  } else if (type === "plan_crew_changed") {
    const label = evt.train_number || `Plan #${evt.plan_id}`;
    const parts = [];
    if (evt.engineer) parts.push(`Engineer: ${evt.engineer}`);
    if (evt.conductor) parts.push(`Conductor: ${evt.conductor}`);
    showToast(`${label} — ${parts.join(" / ")}`, "info");
  } else if (type === "plan_status_changed") {
    const label = evt.train_number || evt.train_name || `Plan #${evt.plan_id}`;
    if (evt.status === "active") {
      showToast(`${label} is now active`, "info");
    } else if (evt.status === "complete") {
      showToast(`${label} complete`, "success");
    }
  }
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

// ── Clock bar (always-visible in ops tab) ─────────────────────────────────────
$("#btn-clock-pause").addEventListener("click", toggleClockPause);
$("#btn-clock-reset").addEventListener("click", async () => {
  const state = await api("POST", "/api/session/clock/start");
  _applyClockState(state); // immediate update for this tab; SSE will sync others
});
