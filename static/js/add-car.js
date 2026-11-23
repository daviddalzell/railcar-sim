// SPDX-FileCopyrightText: 2026 David Dalzell
// SPDX-License-Identifier: MIT

// Photo library, and Add car via photo (incl. the AI vision analysis +
// stylize flow). Loaded as a classic script before app.js. openPhotoLibrary
// and refreshLibraryGrid are called from roster.js (Edit car's library-swap
// flow), layout.js, export-import.js, and settings.js. `addMode` is a bare
// global (not under appState) read directly by layout.js's
// updateDefaultImageOffer() — a pre-existing cross-file coupling preserved
// as-is. Everything else here is self-contained. Shared helpers/appState
// come from helpers.js/state.js.

// ── Photo library ─────────────────────────────────────────────────────────────
let photoLibraryCallback = null;
let selectedLibraryPaths = new Set();

function updateDeleteSelectedBtn() {
  const btn = $("#btn-delete-selected");
  const n = selectedLibraryPaths.size;
  if (n > 0) {
    show(btn);
    $("#selected-count").textContent = n;
  } else {
    hide(btn);
    delete btn.dataset.confirm;
    btn.classList.remove("btn-confirming");
  }
}

async function refreshLibraryGrid() {
  const grid = $("#photo-library-grid");
  grid.innerHTML = `<p class="muted" style="text-align:center;padding:1rem"><span class="spinner"></span>Loading…</p>`;
  try {
    const files = await api("GET", "/api/uploads");
    if (!files.length) {
      grid.innerHTML = emptyState("🖼", "No photos uploaded yet.");
    } else {
      grid.innerHTML = files.map(f => {
        const sel = selectedLibraryPaths.has(f.path) ? " lib-selected" : "";
        const badge = f.is_default
          ? '<span class="lib-badge lib-badge-default">default</span>'
          : f.assigned
            ? '<span class="lib-badge">in use</span>'
            : "";
        const filename = f.path.split("/").pop() || "image.jpg";
        const actions = f.is_default ? "" : `
          <div class="lib-actions">
            <a class="lib-action-btn" href="${f.url}" download="${filename}" title="Download"
               onclick="event.stopPropagation()">⬇</a>
            <button class="lib-action-btn lib-delete-btn" data-path="${f.path}" title="Delete"
                    onclick="event.stopPropagation()">🗑</button>
          </div>`;
        return `
        <div class="lib-thumb${f.assigned ? " lib-assigned" : ""}${sel}"
             data-path="${f.path}" data-url="${f.url}" data-is-default="${f.is_default}">
          <img src="${f.url}" alt="" loading="lazy" width="200" height="150" />
          ${badge}${actions}
        </div>`;
      }).join("");
      $$(".lib-thumb").forEach(el => {
        el.addEventListener("click", () => {
          if (photoLibraryCallback) {
            photoLibraryCallback({ path: el.dataset.path, url: el.dataset.url });
            $("#photo-library-dialog").close();
            return;
          }
          // selection mode — default images cannot be selected for deletion
          if (el.dataset.isDefault === "true") return;
          if (selectedLibraryPaths.has(el.dataset.path)) {
            selectedLibraryPaths.delete(el.dataset.path);
            el.classList.remove("lib-selected");
          } else {
            selectedLibraryPaths.add(el.dataset.path);
            el.classList.add("lib-selected");
          }
          updateDeleteSelectedBtn();
        });
      });
    }
  } catch (err) {
    grid.innerHTML = err.status === 401
      ? `<p class="muted" style="text-align:center">Sign in to access your photo library.</p>`
      : `<p class="muted" style="text-align:center">Failed to load library: ${err.message}</p>`;
  }
  updateDeleteSelectedBtn();
}

async function openPhotoLibrary(onSelect) {
  photoLibraryCallback = onSelect;
  selectedLibraryPaths.clear();
  $("#photo-library-dialog").showModal();
  await refreshLibraryGrid();
}

$("#btn-close-library").addEventListener("click", () => {
  selectedLibraryPaths.clear();
  updateDeleteSelectedBtn();
  $("#photo-library-dialog").close();
});

$("#btn-delete-selected").addEventListener("click", async () => {
  const btn = $("#btn-delete-selected");
  if (!btn.dataset.confirm) {
    btn.dataset.confirm = "1";
    btn.classList.add("btn-confirming");
    const orig = btn.innerHTML;
    btn.textContent = `⚠ Delete ${selectedLibraryPaths.size}? Click again.`;
    setTimeout(() => {
      if (btn.dataset.confirm) {
        delete btn.dataset.confirm;
        btn.classList.remove("btn-confirming");
        btn.innerHTML = orig;
      }
    }, 4000);
    return;
  }
  delete btn.dataset.confirm;
  btn.classList.remove("btn-confirming");
  try {
    const result = await api("POST", "/api/uploads/delete-many", { paths: [...selectedLibraryPaths] });
    selectedLibraryPaths.clear();
    const msg = result.protected
      ? `Deleted ${result.deleted}, skipped ${result.protected} in-use image(s).`
      : `Deleted ${result.deleted} image(s).`;
    showToast(msg, result.protected ? "warning" : "success");
    await refreshLibraryGrid();
  } catch (err) {
    showToast("Delete failed: " + err.message, "error");
  }
});

$("#btn-library-upload").addEventListener("click", () => $("#library-upload-input").click());
$("#library-upload-input").addEventListener("change", async e => {
  const files = Array.from(e.target.files);
  if (!files.length) return;
  const btn = $("#btn-library-upload");
  btn.disabled = true;
  let failed = 0;
  for (let i = 0; i < files.length; i++) {
    btn.textContent = `Uploading ${i + 1}/${files.length}…`;
    try {
      const fd = new FormData();
      fd.append("file", files[i]);
      const token = _authToken();
      const resp = await fetch("/api/cars/upload?skip_analysis=true", {
        method: "POST", body: fd,
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      });
      if (!resp.ok) throw new Error(await resp.text());
    } catch {
      failed++;
    }
  }
  btn.textContent = "⬆ Load File(s)";
  btn.disabled = false;
  e.target.value = "";
  if (failed) showToast(`${failed} file(s) failed to upload.`, "error");
  await refreshLibraryGrid();
});

// ── Add car via photo ─────────────────────────────────────────────────────────
let addMode = "photo"; // "photo" | "manual"
let stylizedPath = null;
let stylizeQuotaExceeded = false;

function showStylizeIdle() {
  show($("#stylize-idle"));
  hide($("#stylize-processing"));
  hide($("#stylize-result"));
  hide($("#stylize-error"));
}

function _applyStylizeQuotaUI() {
  const btn = $("#btn-stylize");
  if (!btn) return;
  btn.disabled = true;
  btn.title = "Image generation requires a paid Gemini API key";
  updateDefaultImageOffer();
}

async function runStylize() {
  if (stylizeQuotaExceeded) return;
  hide($("#stylize-idle"));
  hide($("#stylize-result"));
  hide($("#stylize-error"));
  show($("#stylize-processing"));
  try {
    const result = await api("POST", "/api/cars/stylize", { photo_path: appState.photoPath });
    stylizedPath = result.stylized_path;
    $("#stylize-preview").src = result.url;
    hide($("#stylize-processing"));
    show($("#stylize-result"));
  } catch (err) {
    hide($("#stylize-processing"));
    if (err.status === 402) {
      stylizeQuotaExceeded = true;
      $("#stylize-error-msg").textContent = err.message;
      show($("#stylize-error"));
      show($("#stylize-idle"));
      _applyStylizeQuotaUI();
    } else {
      $("#stylize-error-msg").textContent = "Stylize failed: " + err.message;
      show($("#stylize-error"));
      show($("#stylize-idle"));
    }
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
  appState.photoPath = null;
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
  hide($("#default-image-offer"));
  show($("#car-fields"));
  appState.photoPath = null;
  $("#photo-input").value = "";
  $("#upload-label").textContent = "📷 Click or drop a photo (optional)";
  $("#field-marks").value = "";
  $("#field-number").value = "";
  $("#field-type").value = "other";
  $("#field-color").value = "";
  ["light-weight", "load-limit", "capacity", "built-date", "reweigh-date",
   "reweigh-location", "cots-date", "cots-location"].forEach(id => { $(`#field-${id}`).value = ""; });
  $("#dataplate-details").open = false;
  hide($("#dataplate-ai-hint"));
  updateDefaultImageOffer();
});

async function cancelAddCar() {
  await discardStylized();
  hide($("#add-car-form"));
  hide($("#stylize-section"));
  hide($("#default-image-offer"));
}
$("#btn-cancel-car").addEventListener("click", cancelAddCar);
$("#btn-cancel-car-top").addEventListener("click", cancelAddCar);

function readDataplateFields(prefix) {
  const num = (id) => { const v = $(`#${prefix}${id}`).value.trim(); return v ? parseInt(v, 10) : null; };
  const str = (id) => $(`#${prefix}${id}`).value.trim();
  return {
    light_weight: num("light-weight"),
    load_limit: num("load-limit"),
    capacity: num("capacity"),
    built_date: str("built-date"),
    reweigh_date: str("reweigh-date"),
    reweigh_location: str("reweigh-location"),
    cots_date: str("cots-date"),
    cots_location: str("cots-location"),
  };
}

function applyAnalysis(result) {
  if (result.photo_path) appState.photoPath = result.photo_path;
  $("#field-marks").value = result.reporting_marks || "";
  $("#field-number").value = result.car_number || "";
  $("#field-type").value  = result.car_type || "other";
  $("#field-color").value = result.color || "";
  $("#field-light-weight").value = result.light_weight || "";
  $("#field-load-limit").value = result.load_limit || "";
  $("#field-capacity").value = result.capacity || "";
  $("#field-built-date").value = result.built_date || "";
  $("#field-reweigh-date").value = result.reweigh_date || "";
  $("#field-reweigh-location").value = result.reweigh_location || "";
  $("#field-cots-date").value = result.cots_date || "";
  $("#field-cots-location").value = result.cots_location || "";
  const foundDataplate = [
    result.light_weight, result.load_limit, result.capacity, result.built_date,
    result.reweigh_date, result.reweigh_location, result.cots_date, result.cots_location,
  ].some(v => v !== null && v !== undefined && v !== "");
  $("#dataplate-details").open = foundDataplate;
  if (foundDataplate) show($("#dataplate-ai-hint")); else hide($("#dataplate-ai-hint"));
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
    if (stylizeQuotaExceeded) _applyStylizeQuotaUI();
  }
}

// ── Stylize handlers ──────────────────────────────────────────────────────────
async function discardStylized() {
  if (!stylizedPath) return;
  const path = stylizedPath;
  stylizedPath = null;
  try { await api("POST", "/api/uploads/delete", { path }); } catch { /* best-effort */ }
}

$("#btn-stylize").addEventListener("click", runStylize);

$("#btn-regenerate").addEventListener("click", async () => {
  await discardStylized();
  runStylize();
});

$("#btn-use-stylized").addEventListener("click", () => {
  if (stylizedPath) {
    appState.photoPath = stylizedPath;
    $("#preview-img").src = $("#stylize-preview").src;
  }
  stylizedPath = null;
  hide($("#stylize-section"));
});

$("#btn-keep-original").addEventListener("click", async () => {
  await discardStylized();
  hide($("#stylize-section"));
});

// Library → add car (shared button; branches on addMode)
$("#btn-library-add").addEventListener("click", () => {
  if (addMode === "manual") {
    // Manual mode: just set photo, no analysis
    openPhotoLibrary(({ path, url }) => {
      appState.photoPath = path;
      $("#preview-img").src = url;
      show($("#upload-preview"));
      hide($("#default-image-offer"));
    });
  } else {
    // Photo mode: run vision analysis on selection
    openPhotoLibrary(async ({ path, url }) => {
      $("#preview-img").src = url;
      show($("#upload-preview"));
      hide($("#car-fields"));
      show($("#analyzing-msg"));
      hide($("#vision-error"));
      appState.photoPath = path;
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

function isBrowserUnsupportedImage(file) {
  const ext = file.name.split(".").pop().toLowerCase();
  return ["heic", "heif"].includes(ext) || file.type === "image/heic" || file.type === "image/heif";
}

async function processPhotoFile(file) {
  if (!file) return;

  $("#upload-label").textContent = file.name;
  hide($("#vision-error"));

  const unsupported = isBrowserUnsupportedImage(file);
  if (!unsupported) {
    $("#preview-img").src = URL.createObjectURL(file);
    show($("#upload-preview"));
  }

  const form = new FormData();
  form.append("file", file);

  if (addMode === "manual") {
    try {
      const result = await api("POST", "/api/cars/upload", form);
      if (result.photo_path) {
        appState.photoPath = result.photo_path;
        $("#preview-img").src = photoSrc(result.photo_path);
        show($("#upload-preview"));
      }
      hide($("#default-image-offer"));
    } catch (err) {
      $("#vision-error-msg").textContent = "Upload failed: " + err.message;
      show($("#vision-error"));
    }
    return;
  }

  hide($("#car-fields"));
  show($("#analyzing-msg"));
  try {
    const result = await api("POST", "/api/cars/upload", form);
    if (result.photo_path) {
      $("#preview-img").src = photoSrc(result.photo_path);
      show($("#upload-preview"));
    }
    applyAnalysis(result);
  } catch (err) {
    hide($("#analyzing-msg"));
    $("#vision-error-msg").textContent = "Upload failed: " + err.message;
    show($("#vision-error"));
    show($("#car-fields"));
  }
}

$("#photo-input").addEventListener("change", e => processPhotoFile(e.target.files[0]));

$("#upload-zone").addEventListener("dragover", e => { e.preventDefault(); e.dataTransfer.dropEffect = "copy"; });
$("#upload-zone").addEventListener("drop", e => { e.preventDefault(); processPhotoFile(e.dataTransfer.files[0]); });

$("#btn-retry-vision").addEventListener("click", async () => {
  hide($("#vision-error"));
  hide($("#car-fields"));
  show($("#analyzing-msg"));
  try {
    const result = await api("POST", "/api/cars/analyze-photo", { photo_path: appState.photoPath });
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
    photo_path: appState.photoPath || "",
    ...readDataplateFields("field-"),
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
