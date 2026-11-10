// SPDX-FileCopyrightText: 2026 David Dalzell
// SPDX-License-Identifier: MIT

// Export / Import tab actions: layout ZIP backup download + restore, photo
// library open/purge, and the Import Cars (CSV / JMRI XML) preview dialog.
// Loaded as a classic script before app.js. Shared helpers ($, api, show,
// hide, showToast, withLoading, _authToken, _subscriberId) come from
// helpers.js; openPhotoLibrary / refreshLibraryGrid / loadRoster come from
// app.js but are only invoked inside event handlers (runtime), so load order
// relative to app.js is safe.

// ── Data actions menu ─────────────────────────────────────────────────────────
// Single trigger collapsed on every screen size (issue #65) — see
// closeAllTreeMenus/closeDataMenu in app.js for the outside-click/Escape close.
$("#btn-layout-data-menu").addEventListener("click", (e) => {
  e.stopPropagation();
  const menu = $("#layout-data-menu");
  const wasOpen = menu.classList.contains("open");
  closeDataMenu();
  if (!wasOpen) {
    menu.classList.add("open");
    $("#btn-layout-data-menu").setAttribute("aria-expanded", "true");
  }
});
$("#layout-data-menu .data-menu-panel").addEventListener("click", () => closeDataMenu());

// ── Export / Import ───────────────────────────────────────────────────────────
$("#btn-open-photo-library").addEventListener("click", () => openPhotoLibrary(null));

$("#btn-export-backup").addEventListener("click", async () => {
  const btn = $("#btn-export-backup");
  const orig = btn.textContent;
  btn.disabled = true;
  btn.textContent = "Exporting…";
  try {
    const res = await fetch("/api/export", {
      headers: { "Authorization": `Bearer ${_authToken()}`, "X-Subscriber-Id": _subscriberId },
    });
    if (!res.ok) throw new Error(`Export failed (${res.status})`);
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    const today = new Date().toISOString().slice(0, 10);
    a.href = url;
    a.download = `railcar-backup-${today}.zip`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  } catch (err) {
    showToast("Export failed: " + err.message, "error");
  } finally {
    btn.disabled = false;
    btn.textContent = orig;
  }
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
      await refreshLibraryGrid();
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
    const token = _authToken();
    const result = await fetch("/api/import/cars", {
      method: "POST", body: fd,
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    }).then(async r => {
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
    const token = _authToken();
    const headers = { "Content-Type": "application/json" };
    if (token) headers["Authorization"] = `Bearer ${token}`;
    const resp = await fetch("/api/import/cars/commit", {
      method: "POST",
      headers,
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
