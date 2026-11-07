"use strict";
const el = id => document.getElementById(id);
el("open-about").addEventListener("click", () => el("about-dialog").showModal());
el("close-about").addEventListener("click", () => el("about-dialog").close());
let page = null, offset = 0, sources = [];
let selectedSources = null;
const sourcesModeKey = "booster-ip-service.sources-expanded.v1";
let sourcesExpanded = false;
try { sourcesExpanded = localStorage.getItem(sourcesModeKey) === "true"; } catch (_) {}
function updateSourcesMode() {
  el("sources").classList.toggle("compact", !sourcesExpanded);
  el("source-toolbar").hidden = !sourcesExpanded;
  el("toggle-sources").textContent = sourcesExpanded ? "Collapse" : "Expand";
  el("toggle-sources").setAttribute("aria-expanded", String(sourcesExpanded));
}
el("toggle-sources").addEventListener("click", () => {
  sourcesExpanded = !sourcesExpanded;
  try { localStorage.setItem(sourcesModeKey, String(sourcesExpanded)); } catch (_) {}
  updateSourcesMode();
  renderSources();
});
updateSourcesMode();
let limitMode = "1000";
let outputMode = "list";
const formatterKey = "booster-ip-service.custom-output.v1";
const formatterFields = ["header", "entry", "separator", "footer"];
const savedFormatsKey = "booster-ip-service.saved-output-formats.v1";
let savedFormats = {};
let selectedSavedFormat = null;
let pendingDeleteFormat = null;
function currentFormatter() {
  return Object.fromEntries(formatterFields.map(field => [field, el("output-" + field).value]));
}
function validFormatter(value) {
  return value && typeof value === "object" && formatterFields.every(field => typeof value[field] === "string");
}
function restoreSavedFormats() {
  try {
    const data = JSON.parse(localStorage.getItem(savedFormatsKey) || "{}");
    if (!data || typeof data !== "object" || Array.isArray(data)) return;
    for (const [name, template] of Object.entries(data)) {
      if (name.trim() && name.length <= 60 && validFormatter(template)) savedFormats[name] = template;
    }
  } catch (_) { /* Invalid or unavailable local storage. */ }
}
function activeFormatter() {
  return outputMode === "saved" && selectedSavedFormat && savedFormats[selectedSavedFormat]
    ? savedFormats[selectedSavedFormat] : currentFormatter();
}
function updateOutputMode() {
  for (const mode of ["list", "custom"]) {
    const active = outputMode === mode;
    el("output-" + mode).classList.toggle("active", active);
    el("output-" + mode).setAttribute("aria-pressed", String(active));
  }
  el("output-template-wrap").hidden = outputMode !== "custom";
  renderSavedFormatButtons();
}
function renderSavedFormatButtons() {
  const target = el("saved-output-buttons");
  target.replaceChildren();
  for (const name of Object.keys(savedFormats).sort((a, b) => a.localeCompare(b, undefined, {sensitivity:"base"}))) {
    const wrapper = document.createElement("div");
    wrapper.className = "saved-format-item";
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = name;
    const active = outputMode === "saved" && selectedSavedFormat === name;
    button.className = "page-preset" + (active ? " active" : "");
    button.setAttribute("aria-pressed", String(active));
    button.addEventListener("click", () => {
      selectedSavedFormat = name;
      outputMode = "saved";
      for (const field of formatterFields) el("output-" + field).value = field === "entry" ? "{value}" : field === "separator" ? "\\n" : "";
      saveFormatter();
      updateOutputMode();
      saveOutputSettings();
      renderOutput();
    });
    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "saved-format-remove";
    remove.textContent = "×";
    remove.setAttribute("aria-label", "Remove saved format " + name);
    remove.title = "Remove " + name;
    remove.addEventListener("click", () => {
      pendingDeleteFormat = name;
      el("delete-format-message").textContent = 'Are you sure you want to delete "' + name + '"?';
      el("delete-format-dialog").showModal();
    });
    wrapper.append(button, remove);
    target.append(wrapper);
  }
}

el("cancel-delete-format").addEventListener("click", () => el("delete-format-dialog").close());
el("delete-format-dialog").addEventListener("close", () => { pendingDeleteFormat = null; });
el("confirm-delete-format").addEventListener("click", () => {
  const name = pendingDeleteFormat;
  if (!name || !Object.hasOwn(savedFormats, name)) {
    el("delete-format-dialog").close();
    return;
  }
  const updated = {...savedFormats};
  delete updated[name];
  try {
    localStorage.setItem(savedFormatsKey, JSON.stringify(updated));
  } catch (_) {
    window.alert("Unable to remove the saved format from browser storage.");
    return;
  }
  savedFormats = updated;
  if (selectedSavedFormat === name) {
    selectedSavedFormat = null;
    outputMode = "list";
  }
  el("delete-format-dialog").close();
  updateOutputMode();
  saveOutputSettings();
  renderOutput();
});
function decodeEscapes(value) {
  return value.replace(/\\(n|t|\\)/g, (_, code) =>
    code === "n" ? "\n" : code === "t" ? "\t" : "\\");
}
function formatOutput(values) {
  if (outputMode === "list") return values.join("\n");
  const template = activeFormatter();
  const header = decodeEscapes(template.header);
  const entry = decodeEscapes(template.entry);
  const separator = decodeEscapes(template.separator);
  const footer = decodeEscapes(template.footer);
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
      outputMode,
      selectedSavedFormat
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
    if (settings.outputMode === "saved" && typeof settings.selectedSavedFormat === "string" && savedFormats[settings.selectedSavedFormat]) {
      outputMode = "saved";
      selectedSavedFormat = settings.selectedSavedFormat;
    }
  } catch (_) { /* Ignore corrupt or unavailable storage. */ }
  for (const button of document.querySelectorAll(".page-size-control .page-preset")) {
    const active = button.dataset.limit === limitMode;
    button.classList.toggle("active", active);
    button.setAttribute("aria-pressed", String(active));
  }
  el("custom-limit-wrap").hidden = limitMode !== "custom";
  updateOutputMode();
}

const sourceNotices = new Map();
function setSourceNotice(id, value) {
  sourceNotices.set(id, value);
  const footer = [...document.querySelectorAll(".source-footer")].find(item => item.dataset.sourceId === id);
  if (footer) footer.textContent = value;
}
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
  renderSources();
}
function renderSources() {
  const rows = sources;
  const target = el("sources"); target.replaceChildren();
  if (!sourcesExpanded) {
    for (const row of rows) {
      const chip = node("div", "", "source-chip");
      chip.append(node("span", row.name), node("span", row.data_status, "status " + row.data_status));
      target.append(chip);
    }
    if (!rows.length) target.textContent = "No sources configured.";
    return;
  }
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
    const actions = node("div", "", "source-actions");
    const history = node("button", "History");
    history.type = "button"; history.addEventListener("click", () => showHistory(row));
    actions.append(refresh);
    actions.append(history);
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
  if (limit === null) { page = null; el("output").value = ""; el("output-analysis-text").textContent = "Enter a valid page size to analyze output."; return; }
  if (!selectedSources || selectedSources.size === 0) {
    page = null; el("output").value = ""; el("summary").textContent = "0 selected sources";
    el("output-analysis-text").textContent = "Select at least one source to analyze output.";
    for (const id of ["previous", "next", "copy", "download"]) el(id).disabled = true;
    message("Select at least one source to view output."); return;
  }
  const params = new URLSearchParams({format:el("format").value,family:el("family").value,limit:String(limit),offset:String(offset),sources:[...selectedSources].sort().join(",")});
  page = await api("/api/v1/data?" + params);
  renderOutput();
  const stats = page.analysis;
  if (stats) {
    const freshness = Object.values(page.source_status || {}).some(source => source.data_status === "pending")
      ? "Some source data is pending."
      : Object.values(page.source_status || {}).some(source => source.data_status === "stale")
        ? "Some source data is stale." : "Data is fresh.";
    el("output-analysis-text").textContent = "Complete output contains " + stats.cidr_count.toLocaleString()
      + " CIDRs representing " + stats.ip_count.toLocaleString() + " IPs. " + freshness;
  } else {
    el("output-analysis-text").textContent = "Output analysis is unavailable.";
  }
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
    selectedSavedFormat = null;
    updateOutputMode();
    saveOutputSettings();
    renderOutput();
  });
}
restoreSavedFormats();
el("save-output-format").addEventListener("click", () => {
  el("save-format-form").reset();
  el("save-format-error").textContent = "";
  el("save-format-dialog").showModal();
  el("saved-format-name").focus();
});
el("cancel-save-format").addEventListener("click", () => el("save-format-dialog").close());
el("save-format-form").addEventListener("submit", event => {
  event.preventDefault();
  const name = el("saved-format-name").value.trim();
  if (!name) { el("save-format-error").textContent = "Enter a format name."; return; }
  if (Object.keys(savedFormats).some(existing => existing.toLowerCase() === name.toLowerCase())) {
    el("save-format-error").textContent = "A format with that name already exists.";
    return;
  }
  const updated = {...savedFormats, [name]: currentFormatter()};
  try {
    localStorage.setItem(savedFormatsKey, JSON.stringify(updated));
  } catch (_) {
    el("save-format-error").textContent = "Unable to save in this browser. Check storage settings.";
    return;
  }
  savedFormats = updated;
  el("save-format-dialog").close();
  selectedSavedFormat = name;
  outputMode = "saved";
  for (const field of formatterFields) el("output-" + field).value = field === "entry" ? "{value}" : field === "separator" ? "\\n" : "";
  saveFormatter();
  updateOutputMode();
  saveOutputSettings();
  renderOutput();
});
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
