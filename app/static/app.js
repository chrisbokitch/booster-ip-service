"use strict";
const el = id => document.getElementById(id);
let page = null, offset = 0, sources = [];
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
async function loadData() {
  const params = new URLSearchParams({format:el("format").value,family:el("family").value,limit:el("limit").value,offset:String(offset)});
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
el("previous").addEventListener("click", () => { offset = Math.max(0, offset - Number(el("limit").value)); loadData().catch(e => message(e.message)); });
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
