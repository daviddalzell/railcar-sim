// SPDX-FileCopyrightText: 2026 David Dalzell
// SPDX-License-Identifier: MIT

// Settings tab (tenant name, AI provider + API keys, member management) and
// the account dialog (email, change password, sign out). Loaded as a classic
// script before app.js. loadSettings / _startMembersRefresh / _stopMembersRefresh
// are called from app.js's tab-navigation handler at runtime; everything else
// here is self-contained. Shared helpers/appState come from helpers.js/state.js.

// ── Account dialog ────────────────────────────────────────────────────────────
document.getElementById("account-btn")?.addEventListener("click", () => {
  const dlg = document.getElementById("account-dialog");
  if (!dlg) return;
  document.getElementById("account-email").textContent = window._currentUserEmail || "";
  const tenantName = appState.settings?.name || document.querySelector("title")?.textContent || "";
  document.getElementById("account-tenant").textContent = tenantName;
  document.getElementById("account-pw-sent").style.display = "none";
  dlg.showModal();
});

document.getElementById("close-account-dialog")?.addEventListener("click", () => {
  document.getElementById("account-dialog")?.close();
});

document.getElementById("account-change-pw-btn")?.addEventListener("click", async () => {
  const email = window._currentUserEmail;
  if (!email || !window._sb) return;
  const btn = document.getElementById("account-change-pw-btn");
  btn.disabled = true;
  btn.textContent = "Sending…";
  const { error } = await window._sb.auth.resetPasswordForEmail(email, {
    redirectTo: window.location.origin,
  });
  btn.disabled = false;
  btn.textContent = "Change password";
  document.getElementById("account-pw-sent").style.display = error ? "none" : "";
  if (error) showToast("Could not send reset email: " + error.message, "error");
});

document.getElementById("account-signout-btn")?.addEventListener("click", async () => {
  if (!window._sb) return;
  await window._sb.auth.signOut();
  sessionStorage.removeItem("waypoint_token");
  window.location.reload();
});

// ── Settings tab ──────────────────────────────────────────────────────────────
async function loadMembers() {
  const loading = document.getElementById("members-loading");
  const table   = document.getElementById("members-table");
  const tbody   = document.getElementById("members-body");
  if (!tbody) return;

  let members;
  try {
    members = await api("GET", "/api/tenant-settings/members");
  } catch (err) {
    // Operators don't have access — hide the section silently
    if (err.status === 403) {
      const fieldset = document.getElementById("members-fieldset");
      if (fieldset) fieldset.style.display = "none";
      return;
    }
    if (loading) loading.textContent = "Could not load members.";
    return;
  }
  if (!members || !members.length) {
    if (loading) loading.textContent = "No members yet.";
    if (table) table.style.display = "none";
    return;
  }
  if (loading) loading.style.display = "none";
  if (table) table.style.display = "";

  tbody.innerHTML = members.map(m => {
    const status = !m.is_active ? '<span style="color:var(--pico-muted-color)">Revoked</span>'
      : m.joined_at ? '<span style="color:green">Active</span>'
      : '<span style="color:var(--pico-muted-color)">Pending</span>';
    const roleCtrl = m.is_active
      ? `<select class="member-role-select" data-id="${m.id}" style="padding:0.15rem 0.35rem;font-size:0.8em;height:auto;width:auto;">
           <option value="operator"${m.role==="operator"?" selected":""}>Operator</option>
           <option value="admin"${m.role==="admin"?" selected":""}>Admin</option>
         </select>`
      : `<span style="font-size:0.85em;color:var(--pico-muted-color)">${m.role}</span>`;
    const removeBtn = m.is_active
      ? `<button class="member-remove-btn outline secondary" data-id="${m.id}" style="padding:0.1rem 0.4rem;font-size:0.75em;width:auto;">×</button>`
      : "";
    return `<tr data-member-id="${m.id}">
      <td style="word-break:break-all;">${m.email}</td>
      <td>${roleCtrl}</td>
      <td>${status}</td>
      <td>${removeBtn}</td>
    </tr>`;
  }).join("");
}

document.addEventListener("change", async e => {
  const sel = e.target.closest(".member-role-select");
  if (!sel) return;
  const id = sel.dataset.id;
  const role = sel.value;
  try {
    await api("PATCH", `/api/tenant-settings/members/${id}`, { role });
    showToast("Role updated", "success");
  } catch (err) {
    showToast("Failed to update role: " + err.message, "error");
    await loadMembers(); // revert UI
  }
});

document.addEventListener("click", async e => {
  const btn = e.target.closest(".member-remove-btn");
  if (!btn) return;
  if (!confirm("Remove this member? They will lose access immediately.")) return;
  const id = btn.dataset.id;
  try {
    await api("DELETE", `/api/tenant-settings/members/${id}`);
    showToast("Member removed", "success");
    await loadMembers();
  } catch (err) {
    showToast("Failed to remove member: " + err.message, "error");
  }
});

// Refresh button for members
document.getElementById("members-refresh-btn")?.addEventListener("click", () => loadMembers());

// Auto-refresh members list every 15 s while the settings tab is visible
let _membersRefreshTimer = null;
function _startMembersRefresh() {
  _stopMembersRefresh();
  loadMembers();
  _membersRefreshTimer = setInterval(loadMembers, 60_000);
}
function _stopMembersRefresh() {
  if (_membersRefreshTimer) { clearInterval(_membersRefreshTimer); _membersRefreshTimer = null; }
}

function setLayoutTitle(name) {
  const el = $("#layout-setup-title");
  if (el) el.textContent = (name && name.trim()) || "My Layout";
}

async function loadSettings() {
  const data = await api("GET", "/api/tenant-settings");
  if (!data) return;

  const nameInput = $("#settings-tenant-name");
  if (nameInput && data.name !== undefined) nameInput.value = data.name;
  setLayoutTitle(data.name);

  const providerSel = $("#settings-provider");
  if (providerSel) providerSel.value = data.vision_provider || "gemini";

  const note = $("#settings-source-note");
  if (note) note.textContent = data.source === "env"
    ? "Running in local dev mode — keys are read from environment variables and cannot be changed here."
    : "";

  const setStatus = (id, field, set) => {
    const el = $(id);
    if (!el) return;
    if (set) {
      el.innerHTML = `✓ Key is set &nbsp;<a href="#" class="clear-key-link" data-field="${field}" style="color:#c0392b;font-size:0.85em;">× Clear</a>`;
    } else {
      el.textContent = "No key configured";
    }
  };
  setStatus("#settings-gemini-status",    "gemini_api_key",    data.gemini_key_set);
  setStatus("#settings-anthropic-status", "anthropic_api_key", data.anthropic_key_set);
  setStatus("#settings-openai-status",    "openai_api_key",    data.openai_key_set);

  const saveBtn = $("#settings-save-btn");
  if (saveBtn && data.source === "env") saveBtn.disabled = true;

  if (document.getElementById("demo-banner")) {
    const notice = document.getElementById("settings-demo-notice");
    if (notice) notice.style.display = "";
    document.querySelectorAll("#settings-content input, #settings-content select, #settings-content button, #settings-content a.clear-key-link")
      .forEach(el => { el.disabled = true; });
  }
}

$("#settings-save-btn")?.addEventListener("click", async () => {
  const msg = $("#settings-save-msg");
  const body = {
    name: $("#settings-tenant-name")?.value?.trim() || null,
    vision_provider: $("#settings-provider")?.value || null,
  };
  const gemini    = $("#settings-gemini-key")?.value;
  const anthropic = $("#settings-anthropic-key")?.value;
  const openai    = $("#settings-openai-key")?.value;
  if (gemini)    body.gemini_api_key    = gemini;
  if (anthropic) body.anthropic_api_key = anthropic;
  if (openai)    body.openai_api_key    = openai;

  try {
    const result = await api("PATCH", "/api/tenant-settings", body);
    if (result?.ok) {
      if (msg) msg.textContent = "Saved.";
      ["#settings-gemini-key", "#settings-anthropic-key", "#settings-openai-key"].forEach(id => {
        const el = $(id);
        if (el) el.value = "";
      });
      await loadSettings();
      setTimeout(() => { if (msg) msg.textContent = ""; }, 3000);
    }
  } catch (err) {
    if (msg) msg.textContent = err.message || "Failed to save settings.";
  }
});

document.addEventListener("click", async e => {
  const delBtn = e.target.closest(".lib-delete-btn");
  if (delBtn) {
    delBtn.disabled = true;
    const path = delBtn.dataset.path;
    try {
      const result = await api("POST", "/api/uploads/delete-many", { paths: [path] });
      if (result?.deleted > 0) {
        showToast("Image deleted", "success");
        selectedLibraryPaths.delete(path);
        await refreshLibraryGrid();
      } else {
        showToast("Image is in use and cannot be deleted", "warning");
        delBtn.disabled = false;
      }
    } catch {
      delBtn.disabled = false;
    }
    return;
  }
});

document.addEventListener("click", async e => {
  const link = e.target.closest(".clear-key-link");
  if (!link) return;
  e.preventDefault();
  const field = link.dataset.field;
  const result = await api("PATCH", "/api/tenant-settings", { [field]: "" });
  if (result?.ok) await loadSettings();
});

$("#invite-send-btn")?.addEventListener("click", async () => {
  const email = $("#invite-email")?.value?.trim();
  const role  = $("#invite-role")?.value || "operator";
  const msg   = $("#invite-msg");
  if (!email) { if (msg) msg.textContent = "Enter an email address."; return; }
  try {
    const result = await api("POST", "/api/tenant-settings/invite", { email, role });
    if (result?.ok) {
      if (msg) msg.textContent = `Invite sent to ${email}.`;
      if ($("#invite-email")) $("#invite-email").value = "";
      setTimeout(() => { if (msg) msg.textContent = ""; }, 4000);
      loadMembers();
    }
  } catch (err) {
    if (msg) msg.textContent = err.message || "Failed to send invite.";
  }
});
