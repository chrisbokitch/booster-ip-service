"use strict";
const el = id => document.getElementById(id);
let page = null, offset = 0, sources = [];
let selectedSources = null;
let limitMode = "1000";
let outputMode = "list";
const formatterKey = "booster-ip-service.custom-output.v1";
const formatterFields = ["header", "entry", "separator", "footer"];
function decodeEscapes(value) {
  return value.replace(/\\(n|t|\\)/g, (_, code) =>
    code === "n" ? "\n" : code === "t" ? "\t" : "\\");
}
function formatOutput(values) {
  if (outputMode === "list") return values.join("\n");
  const header = decodeEscapes(el("output-header").value);
  const entry = decodeEscapes(el("output-entry").value);
  const separator = decodeEscapes(el("output-separator").value);
  const footer = decodeEscapes(el("output-footer").value);
  return header + values.map(value => entry.replaceAll("{value}", value)).join(separator) + footer;
}
function renderOutput() {
  el("output").value = page ? formatOutput(page.data) : "";
}
function saveFormatter() {
  try {
    const settings = Object.fromEntries(formatterFields.map(field => [field, el("output-" + field).value]));
    localStorage.setItem(formatterKey, JSON.stringify(settings));
  } catch (_) { /* Storage may be disabled; the formatter still works for this session. */ }
}
function restoreFormatter() {
  try {
    const settings = JSON.parse(localStorage.getItem(formatterKey) || "null");
    if (!settings || typeof settings !== "object") return;
    for (const field of formatterFields) {
      if (typeof settings[field] === "string") el("output-" + field).value = settings[field];
    }
  } catch (_) { /* Ignore unavailable or invalid browser storage. */ }
}

const settingsKey = "booster-ip-service.output-settings.v1";
let savedSourceIds = null;
function saveOutputSettings() {
  try {
    localStorage.setItem(settingsKey, JSON.stringify({
      sources: [...(selectedSources || [])],
      format: el("format").value,
      family: el("family").value,
      limitMode,
      limit: el("limit").value,
      outputMode
    }));
  } catch (_) { /* Local storage may be unavailable. */ }
}
function restoreOutputSettings() {
  try {
    const settings = JSON.parse(localStorage.getItem(settingsKey) || "null");
    if (!settings || typeof settings !== "object") return;
    if (Array.isArray(settings.sources) && settings.sources.every(id => typeof id === "string"))
      savedSourceIds = settings.sources;
    if (["cidr", "ip"].includes(settings.format)) el("format").value = settings.format;
    if (["all", "ipv4", "ipv6"].includes(settings.family)) el("family").value = settings.family;
    if (["1000", "10000", "custom"].includes(settings.limitMode)) limitMode = settings.limitMode;
    if (typeof settings.limit === "string" && /^[0-9]+$/.test(settings.limit)
        && Number(settings.limit) >= 1 && Number(settings.limit) <= 1000000)
      el("limit").value = settings.limit;
    if (["list", "custom"].includes(settings.outputMode)) outputMode = settings.outputMode;
  } catch (_) { /* Ignore corrupt or unavailable storage. */ }
  for (const button of document.querySelectorAll(".page-size-control .page-preset")) {
    const active = button.dataset.limit === limitMode;
    button.classList.toggle("active", active);
    button.setAttribute("aria-pressed", String(active));
  }
  el("custom-limit-wrap").hidden = limitMode !== "custom";
  for (const mode of ["list", "custom"]) {
    const active = mode === outputMode;
    el("output-" + mode).classList.toggle("active", active);
    el("output-" + mode).setAttribute("aria-pressed", String(active));
  }
  el("output-template-wrap").hidden = outputMode !== "custom";
}

const sourceNotices = new Map();
function setSourceNotice(id, value) {
  sourceNotices.set(id, value);
  const footer = [...document.querySelectorAll(".source-footer")].find(item => item.dataset.sourceId === id);
  if (footer) footer.textContent = value;
}
let editingSource = null;
let editMode = false;
function setEditMode(enabled) {
  editMode = enabled;
  el("toggle-edit").textContent = enabled ? "Cancel" : "Edit";
  el("toggle-edit").setAttribute("aria-pressed", String(enabled));
  el("add-source").hidden = !enabled;
  if (!enabled && el("source-dialog").open) el("source-dialog").close();
  loadSources().catch(error => message(error.message));
}
el("toggle-edit").addEventListener("click", () => {
  if (editMode) setEditMode(false);
  else el("edit-warning-dialog").showModal();
});
el("confirm-edit-warning").addEventListener("click", () => {
  el("edit-warning-dialog").close();
  setEditMode(true);
});
el("cancel-edit-warning").addEventListener("click", () => el("edit-warning-dialog").close());
async function api(url, options) {
  const response = await fetch(url, {cache:"no-store", ...options});
  if (!response.ok) {
    let message = response.statusText;
    try { const body = await response.json(); message = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail); } catch {}
    throw new Error(message || "Request failed");
  }
  if (response.status === 204) return null;
  return response.json();
}
function message(value) { el("message").textContent = value; }
function fmtDate(value) { return value ? new Date(value).toLocaleString() : "Never"; }
function node(tag, text, className) { const element = document.createElement(tag); element.textContent = text; if (className) element.className = className; return element; }
async function loadSources() {
  const rows = await api("/api/v1/sources");
  sources = rows;
  const enabledIds = rows.filter(row => row.enabled).map(row => row.id);
  if (selectedSources === null) selectedSources = new Set(savedSourceIds === null ? enabledIds : savedSourceIds.filter(id => enabledIds.includes(id)));
  else selectedSources = new Set([...selectedSources].filter(id => enabledIds.includes(id)));
  const selection = el("source-selection"); selection.replaceChildren();
  for (const row of rows) {
    const label = node("label", "", "source-choice");
    const checkbox = document.createElement("input");
    checkbox.type = "checkbox"; checkbox.value = row.id;
    checkbox.checked = selectedSources.has(row.id);
    checkbox.disabled = !row.enabled;
    checkbox.addEventListener("change", () => {
      if (checkbox.checked) selectedSources.add(row.id);
      else selectedSources.delete(row.id);
      saveOutputSettings();
      offset = 0; loadData().catch(e => message(e.message));
    });
    label.append(checkbox, node("span", row.name + (row.enabled ? "" : " (disabled)")));
    selection.append(label);
  }
  const target = el("sources"); target.replaceChildren();
  for (const row of rows) {
    const card = node("article", "", "source");
    const heading = node("div", "", "source-heading");
    heading.append(node("h3", row.name), node("span", row.data_status, "status " + row.data_status));
    const inputType = row.format === "cidr_text" ? "CIDR blocks" : "IPs";
    card.append(heading, node("p", row.record_count.toLocaleString() + " stored " + inputType));
    card.append(node("p", row.cidr_count.toLocaleString() + " aggregated CIDR blocks"));
    card.append(node("p", "Last success: " + fmtDate(row.last_success)));
    if (row.refresh_interval_minutes) card.append(node("p", row.enabled ? "Next refresh: " + fmtDate(row.next_refresh) : "Automatic refresh paused (disabled)"));
    if (row.last_error) card.append(node("p", "Last error: " + row.last_error));
    const refresh = node("button", "Refresh");
    refresh.type = "button"; refresh.disabled = !row.enabled;
    refresh.addEventListener("click", async () => {
      refresh.disabled = true; refresh.textContent = "Refreshing…"; setSourceNotice(row.id, "Refreshing…");
      try {
        await api("/api/v1/sources/" + encodeURIComponent(row.id) + "/refresh", {method:"POST"});
        setSourceNotice(row.id, "Refresh complete.");
        await loadSources(); offset = 0; await loadData();
      } catch (error) {
        setSourceNotice(row.id, error.message === "Source refresh already in progress"
          ? row.name + " is already refreshing. No additional refresh was started."
          : "Refresh failed: " + error.message);
        await loadSources();
      }
    });
    const edit = node("button", "Edit");
    edit.type = "button"; edit.addEventListener("click", () => openSourceDialog(row));
    const remove = node("button", "Remove");
    remove.type = "button"; remove.addEventListener("click", async () => {
      if (!confirm("Remove " + row.name + " and its stored snapshot and history?")) return;
      try {
        await api("/api/v1/sources/" + encodeURIComponent(row.id), {method:"DELETE"});
        selectedSources.delete(row.id);
        await loadSources(); offset = 0; await loadData();
        const removed = node("article", "", "source source-removed");
        removed.append(node("h3", row.name));
        const removedFooter = node("div", "Source removed.", "source-footer");
        removedFooter.setAttribute("role", "status");
        removed.append(removedFooter);
        el("sources").append(removed);
        sourceNotices.delete(row.id);
      } catch (error) { setSourceNotice(row.id, "Remove failed: " + error.message); }
    });
    const actions = node("div", "", "source-actions");
    const history = node("button", "History");
    history.type = "button"; history.addEventListener("click", () => showHistory(row));
    actions.append(refresh);
    if (editMode) actions.append(edit);
    actions.append(history);
    if (editMode) actions.append(remove);
    card.append(actions);
    const footer = node("div", sourceNotices.get(row.id) || "", "source-footer");
    footer.dataset.sourceId = row.id;
    footer.setAttribute("role", "status");
    footer.setAttribute("aria-live", "polite");
    card.append(footer); target.append(card);
  }
  if (!rows.length) target.textContent = "No sources configured.";
}
function pageSize() {
  const input = el("limit");
  if (limitMode !== "custom") return Number(limitMode);
  const value = input.value.trim() === "" ? NaN : Number(input.value);
  if (!Number.isInteger(value) || value < 1 || value > 1000000) {
    input.setCustomValidity("Enter a whole number from 1 to 1,000,000.");
    input.reportValidity();
    return null;
  }
  input.setCustomValidity("");
  return value;
}
async function loadData() {
  const limit = pageSize();
  if (limit === null) { page = null; el("output").value = ""; return; }
  if (!selectedSources || selectedSources.size === 0) {
    page = null; el("output").value = ""; el("summary").textContent = "0 selected sources";
    for (const id of ["previous", "next", "copy", "download"]) el(id).disabled = true;
    message("Select at least one source to view output."); return;
  }
  const params = new URLSearchParams({format:el("format").value,family:el("family").value,limit:String(limit),offset:String(offset),sources:[...selectedSources].sort().join(",")});
  page = await api("/api/v1/data?" + params);
  renderOutput();
  el("summary").textContent = page.total.toLocaleString() + " total · " + (page.complete ? "Complete" : "Missing source data");
  el("previous").disabled = offset === 0;
  el("next").disabled = !page.has_more;
  el("copy").disabled = !page.count;
  el("download").disabled = !page.count;
  message(page.count ? "Showing " + (offset + 1).toLocaleString() + "–" + (offset + page.count).toLocaleString() + " of " + page.total.toLocaleString() : "No records on this page.");
}
for (const mode of ["list", "custom"]) {
  el("output-" + mode).addEventListener("click", () => {
    outputMode = mode;
    for (const option of ["list", "custom"]) {
      const active = option === mode;
      el("output-" + option).classList.toggle("active", active);
      el("output-" + option).setAttribute("aria-pressed", String(active));
    }
    el("output-template-wrap").hidden = mode !== "custom";
    saveOutputSettings();
    renderOutput();
  });
}
restoreFormatter();
for (const field of formatterFields) {
  el("output-" + field).addEventListener("input", () => { saveFormatter(); renderOutput(); });
}
async function refreshAll() { try { await loadSources(); await loadData(); } catch (error) { message("Unable to load data: " + error.message); } }
for (const id of ["format","family"]) el(id).addEventListener("change", () => { saveOutputSettings(); offset = 0; loadData().catch(e => message(e.message)); });
for (const button of document.querySelectorAll(".page-size-control .page-preset")) {
  button.addEventListener("click", () => {
    limitMode = button.dataset.limit;
    for (const other of document.querySelectorAll(".page-size-control .page-preset")) {
      const active = other === button;
      other.classList.toggle("active", active);
      other.setAttribute("aria-pressed", String(active));
    }
    el("custom-limit-wrap").hidden = limitMode !== "custom";
    saveOutputSettings();
    if (limitMode === "custom") el("limit").focus();
    else { el("limit").setCustomValidity(""); offset = 0; loadData().catch(e => message(e.message)); }
  });
}
el("limit").addEventListener("change", () => {
  if (limitMode === "custom") { saveOutputSettings(); offset = 0; loadData().catch(e => message(e.message)); }
});
async function showHistory(row) {
  el("history-title").textContent = row.name + " — Refresh history";
  el("history-content").textContent = "Loading…";
  el("history-dialog").showModal();
  try {
    const entries = await api("/api/v1/sources/" + encodeURIComponent(row.id) + "/history");
    const table = document.createElement("table");
    const head = document.createElement("tr");
    for (const label of ["Time", "Trigger", "Result", "Records / error"]) head.append(node("th", label));
    table.append(head);
    for (const entry of entries) {
      const tr = document.createElement("tr");
      tr.append(node("td", fmtDate(entry.at)), node("td", entry.trigger === "scheduled" ? "Scheduled" : entry.trigger === "manual" ? "Manual" : "Unknown"), node("td", entry.success ? "Success" : "Failed"),
        node("td", entry.success ? String(entry.count) : (entry.error || "Unknown error")));
      table.append(tr);
    }
    el("history-content").replaceChildren(entries.length ? table : node("p", "No refreshes recorded."));
  } catch (error) { el("history-content").textContent = error.message; }
}
el("close-history").addEventListener("click", () => el("history-dialog").close());
function updateIntervalInput() {
  const custom = el("source-interval").value === "custom";
  el("source-custom-interval-wrap").hidden = !custom;
  el("source-custom-interval").required = custom;
}
el("source-interval").addEventListener("change", updateIntervalInput);
function openSourceDialog(row = null) {
  editingSource = row ? row.id : null;
  el("source-form").reset();
  el("source-form-title").textContent = row ? "Edit source" : "Add source";
  el("source-id").disabled = !!row;
  el("source-id").value = row?.id || "";
  el("source-name").value = row?.name || "";
  el("source-url").value = row?.url || "";
  el("source-format").value = row?.format || "cidr_text";
  el("source-json-path").value = row?.json_path || "";
  el("source-enabled").checked = row ? !!row.enabled : true;
  const interval = row?.refresh_interval_minutes;
  el("source-interval").value = interval == null ? "" : ([60,360,720,1440].includes(interval) ? String(interval) : "custom");
  if (interval != null) el("source-custom-interval").value = String(interval);
  updateIntervalInput();
  el("source-form-error").textContent = "";
  el("source-dialog").showModal();
}
el("add-source").addEventListener("click", () => openSourceDialog());
el("cancel-source").addEventListener("click", () => el("source-dialog").close());
el("source-form").addEventListener("submit", async event => {
  event.preventDefault();
  const payload = {
    name: el("source-name").value.trim(), url: el("source-url").value.trim(),
    format: el("source-format").value, json_path: el("source-json-path").value.trim() || null,
    enabled: el("source-enabled").checked,
    refresh_interval_minutes: el("source-interval").value === "" ? null : Number(el("source-interval").value === "custom" ? el("source-custom-interval").value : el("source-interval").value)
  };
  if (!editingSource) payload.id = el("source-id").value.trim();
  const endpoint = editingSource ? "/api/v1/sources/" + encodeURIComponent(editingSource) : "/api/v1/sources";
  const save = el("save-source"); save.disabled = true;
  try {
    const result = await api(endpoint, {method: editingSource ? "PUT" : "POST",
      headers: {"Content-Type":"application/json"}, body: JSON.stringify(payload)});
    el("source-dialog").close();
    if (!editingSource && payload.enabled) selectedSources.add(payload.id);
    await loadSources(); offset = 0; await loadData();
    sourceMessage(result.snapshot_cleared ? "Source saved. Refresh it to load the new feed." : "Source saved.");
  } catch (error) { el("source-form-error").textContent = error.message; }
  finally { save.disabled = false; }
});
el("refresh-all").addEventListener("click", async () => {
  const button = el("refresh-all"); button.disabled = true; button.textContent = "Refreshing…";
  message("Refreshing all enabled sources…");
  try {
    const result = await api("/api/v1/sources/refresh-all", {method:"POST"});
    await loadSources(); offset = 0; await loadData();
    const skipped = result.results.filter(item => item.skipped).map(item => item.source);
    message("Refresh complete: " + result.succeeded + " succeeded, " + result.failed + " failed, "
      + result.skipped + " skipped."
      + (skipped.length ? " Already refreshing (no additional refresh started): " + skipped.join(", ") + "." : ""));
  } catch (error) { message("Refresh all failed: " + error.message); }
  finally { button.disabled = false; button.textContent = "Refresh all"; }
});
el("reload").addEventListener("click", refreshAll);
el("select-all").addEventListener("click", () => {
  selectedSources = new Set(sources.filter(row => row.enabled).map(row => row.id));
  for (const checkbox of el("source-selection").querySelectorAll("input")) checkbox.checked = selectedSources.has(checkbox.value);
  saveOutputSettings();
  offset = 0; loadData().catch(e => message(e.message));
});
el("previous").addEventListener("click", () => { offset = Math.max(0, offset - (page ? page.limit : 1000)); loadData().catch(e => message(e.message)); });
el("next").addEventListener("click", () => { if (page && page.next_offset !== null) { offset = page.next_offset; loadData().catch(e => message(e.message)); } });
el("copy").addEventListener("click", async () => { try { await navigator.clipboard.writeText(el("output").value); message("Page copied."); } catch { el("output").select(); message("Clipboard unavailable; select and copy the text manually."); } });
el("download").addEventListener("click", () => {
  if (!page || !page.count) return;
  const blob = new Blob([el("output").value + "\n"], {type:"text/plain;charset=utf-8"});
  const url = URL.createObjectURL(blob), link = document.createElement("a");
  link.href = url; link.download = "booster-" + page.format + "-" + page.offset + ".txt"; link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
});
restoreOutputSettings();
refreshAll();
