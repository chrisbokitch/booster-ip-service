"use strict";
const el = id => document.getElementById(id);
let page = null, offset = 0, sources = [];
let selectedSources = null;
async function api(url, options) {
  const response = await fetch(url, {cache:"no-store", ...options});
  if (!response.ok) {
    let message = response.statusText;
    try { const body = await response.json(); message = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail); } catch {}
    throw new Error(message || "Request failed");
  }
  return response.json();
}
function message(value) { el("message").textContent = value; }
function fmtDate(value) { return value ? new Date(value).toLocaleString() : "Never"; }
function node(tag, text, className) { const element = document.createElement(tag); element.textContent = text; if (className) element.className = className; return element; }
async function loadSources() {
  const rows = await api("/api/v1/sources");
  sources = rows;
  const enabledIds = rows.filter(row => row.enabled).map(row => row.id);
  if (selectedSources === null) selectedSources = new Set(enabledIds);
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
      offset = 0; loadData().catch(e => message(e.message));
    });
    label.append(checkbox, node("span", row.name + (row.enabled ? "" : " (disabled)")));
    selection.append(label);
  }
  const target = el("sources"); target.replaceChildren();
  for (const row of rows) {
    const card = node("article", "", "source");
    card.append(node("h3", row.name), node("p", row.id + " · " + row.record_count + " stored records"));
    card.append(node("p", row.data_status, "status " + row.data_status));
    card.append(node("p", "Last success: " + fmtDate(row.last_success)));
    if (row.last_error) card.append(node("p", "Last error: " + row.last_error));
    const refresh = node("button", "Refresh");
    refresh.type = "button"; refresh.disabled = !row.enabled;
    refresh.addEventListener("click", async () => {
      refresh.disabled = true; refresh.textContent = "Refreshing…"; message("Refreshing " + row.name + "…");
      try {
        await api("/api/v1/sources/" + encodeURIComponent(row.id) + "/refresh", {method:"POST"});
        await loadSources(); offset = 0; await loadData(); message(row.name + " refreshed.");
      } catch (error) { message("Refresh failed: " + error.message); await loadSources(); }
    });
    card.append(refresh); target.append(card);
  }
  if (!rows.length) target.textContent = "No sources configured.";
}
function pageSize() {
  const input = el("limit");
  const value = Number(input.value);
  if (!Number.isInteger(value) || value < 1 || value > 10000) {
    input.setCustomValidity("Enter a whole number from 1 to 10,000.");
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
  el("output").value = page.data.join("\n");
  el("summary").textContent = page.total.toLocaleString() + " total · " + (page.complete ? "Complete" : "Missing source data");
  el("previous").disabled = offset === 0;
  el("next").disabled = !page.has_more;
  el("copy").disabled = !page.count;
  el("download").disabled = !page.count;
  message(page.count ? "Showing " + (offset + 1).toLocaleString() + "–" + (offset + page.count).toLocaleString() + " of " + page.total.toLocaleString() : "No records on this page.");
}
async function refreshAll() { try { await loadSources(); await loadData(); } catch (error) { message("Unable to load data: " + error.message); } }
for (const id of ["format","family","limit"]) el(id).addEventListener("change", () => { offset = 0; loadData().catch(e => message(e.message)); });
el("reload").addEventListener("click", refreshAll);
el("select-all").addEventListener("click", () => {
  selectedSources = new Set(sources.filter(row => row.enabled).map(row => row.id));
  for (const checkbox of el("source-selection").querySelectorAll("input")) checkbox.checked = selectedSources.has(checkbox.value);
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
refreshAll();
