// SPDX-FileCopyrightText: 2026 David Dalzell
// SPDX-License-Identifier: MIT

// Shared mutable state, read/written by 2+ frontend sections (Roster,
// Waybills, Operations, Session, Layout, Dispatcher, Settings). Exposed as
// a single global object — not individual globals — because a plain `let x`
// in one classic <script> can't be reassigned from another script; `appState.x`
// can, since every script shares one mutable object. Named `appState` (not
// `state`) because `state` is already used locally all over app.js (e.g.
// `_applyClockState(state)`, `getTreeCollapseState()`'s local `state`).
//
// Single-section state (used by only one part of the app — e.g. dispatchPlans,
// commodityMap, selectedCarId) stays as a local `let` in whichever file owns
// it; it doesn't belong here.
//
// Loaded as a classic (non-module) script, before app.js, so this `const`
// declaration becomes a shared global both files see.
const appState = {
  cars: [],
  locations: [],
  industries: [],
  switchingAreas: [],
  carTypes: [],
  waybillPool: [],
  session: null,
  settings: null,
  opsMode: "free",
  photoPath: null,
};
