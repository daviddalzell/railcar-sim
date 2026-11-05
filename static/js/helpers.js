// SPDX-FileCopyrightText: 2026 David Dalzell
// SPDX-License-Identifier: MIT

// Generic, dependency-free leaf utilities used by every frontend section:
// DOM shorthands, the API fetch wrapper, toast notifications, and small
// render/state helpers. Loaded as a classic (non-module) script, before
// app.js, so these become shared globals (same mechanism as state.js).

const $ = (sel, ctx = document) => ctx.querySelector(sel);
const $$ = (sel, ctx = document) => [...ctx.querySelectorAll(sel)];

// Unique ID for this browser tab, used to suppress self-notifications.
const _subscriberId = crypto.randomUUID();

function track(eventName, params = {}) {
  if (typeof gtag === "undefined") return;
  gtag("event", eventName, {
    is_demo: !!document.getElementById("demo-banner"),
    ...params,
  });
}

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
  opts.headers["X-Subscriber-Id"] = _subscriberId;
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
  if (res.status === 451) {
    const d = await res.json().catch(() => ({}));
    const err = new Error(d.detail || "AI features unavailable in your region");
    err.status = 451;
    const dlg = document.getElementById("ai-region-dialog");
    if (dlg && !dlg.open) dlg.showModal();
    throw err;
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
