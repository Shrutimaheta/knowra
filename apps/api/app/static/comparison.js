"use strict";

async function loadComparisonDemo(button) {
  button.disabled = true;
  try {
    const files = await Promise.all([2025, 2026].map(async year => {
      const response = await fetch(`/static/demo/policy-${year}.pdf`);
      if (!response.ok) throw Error("The demonstration files could not be loaded.");
      return response.blob();
    }));
    const first = new FormData();
    first.append("file", files[0], "Comparison demo - Workplace policy.pdf");
    first.append("category", "People");
    first.append("visibility", "private");
    const created = await api("/documents", {method: "POST", body: first});
    const next = new FormData();
    next.append("file", files[1], "Workplace policy - 2026.pdf");
    try {
      await api(`/documents/${created.id}/versions`, {method: "POST", body: next});
    } catch (error) {
      throw Error(`The first demo version was saved. Add the second version from the source viewer. ${error.message}`);
    }
    await navigate("documents");
    toast("Two fictional policy versions uploaded. Open Compare versions when both are Ready.");
  } catch (error) { toast(error.message); }
  finally { if (button.isConnected) button.disabled = false; }
}

function highlightedText(text, ranges) {
  const characters = Array.from(text);
  let result = "", offset = 0;
  for (const range of ranges) {
    result += esc(characters.slice(offset, range.start).join(""));
    result += `<mark>${esc(characters.slice(range.start, range.end).join(""))}</mark>`;
    offset = range.end;
  }
  return result + esc(characters.slice(offset).join(""));
}

async function showEvidence(documentId, versionId, pageNumber, evidence, pageText) {
  const panel = $("#evidence-panel");
  const key = `${documentId}/${versionId}`;
  if (!panel) return;
  panel.innerHTML = `<p class="muted" role="status">Locating the supporting passage on page ${pageNumber}… Scanned pages may take longer.</p>`;
  try {
    const result = await post(`/documents/${documentId}/versions/${versionId}/evidence`, {page: pageNumber, text: evidence.slice(0,4000)});
    if ($("#evidence-panel") !== panel || panel.dataset.sourceKey !== key) return;
    const paragraph = $(`#source-page-${pageNumber} .extracted-page-text`);
    if (paragraph) paragraph.innerHTML = highlightedText(pageText, result.ranges);
    panel.innerHTML = `<section class="evidence-result"><h3>Supporting evidence · page ${pageNumber}</h3><p class="muted">${esc(result.notice)}</p>${result.image ? `<img class="evidence-image" alt="Original source page ${pageNumber} with matching evidence highlighted" src="${result.image}">` : ""}${result.ranges.length ? `<p class="evidence-excerpt">${result.ranges.map(r => `<mark>${esc(Array.from(pageText).slice(r.start, r.end).join(""))}</mark>`).join(" … ")}</p>` : ""}</section>`;
    panel.scrollIntoView({block: "start"});
  } catch (error) {
    if ($("#evidence-panel") === panel) panel.innerHTML = `<p class="error">${esc(error.message)} You can still inspect the source below.</p>`;
  }
}

async function compareModal(documentId, fromVersion, toVersion) {
  try {
    const versions = await api(`/documents/${documentId}/versions`);
    const ready = versions.filter(v => v.status === "ready");
    const options = selected => versions.map(v => `<option value="${v.id}" ${v.id === selected ? "selected" : ""} ${v.status !== "ready" ? "disabled" : ""}>v${v.number} · ${esc(v.filename)}${v.status !== "ready" ? ` (${esc(v.status)})` : ""}</option>`).join("");
    modal(`<div class="eyebrow">DOCUMENT CHANGE REVIEW</div><h2>What changed?</h2><p class="muted">Compare two saved versions. Follow each change to the original evidence.</p><form id="compare-form"><div class="compare-selectors"><label>Before<select id="compare-before">${options(ready.find(v => v.id === fromVersion)?.id || ready[1]?.id || ready[0]?.id)}</select></label><label>After<select id="compare-after">${options(ready.find(v => v.id === toVersion)?.id || ready[0]?.id)}</select></label></div><div class="toolbar"><button class="primary" ${ready.length < 2 ? "disabled" : ""}>Compare versions</button><button type="button" class="secondary" id="refresh-comparison">Refresh versions</button></div></form><div id="comparison-result" aria-live="polite">${ready.length < 2 ? '<p class="muted">Add a second version using “Add a new version” in the source viewer, then wait for both versions to finish indexing.</p>' : ""}</div>`);
    $("#modal").classList.add("comparison-modal");
    $("#refresh-comparison").onclick = () => compareModal(documentId, fromVersion, toVersion);
    for (const selector of ["#compare-before", "#compare-after"]) $(selector).onchange = () => { $("#comparison-result").innerHTML = '<p class="muted">Click Compare versions to review this selection.</p>'; };
    $("#compare-form").onsubmit = async event => {
      event.preventDefault();
      const target = $("#comparison-result");
      const button = event.target.querySelector('button[type="submit"], button.primary');
      button.disabled = true;
      target.innerHTML = '<p class="muted" role="status">Comparing the extracted text…</p>';
      try {
        const query = new URLSearchParams({from_version: $("#compare-before").value, to_version: $("#compare-after").value});
        const result = await api(`/documents/${documentId}/compare?${query}`);
        if ($("#comparison-result") !== target) return;
        renderComparison(target, documentId, result);
      } catch (error) {
        if ($("#comparison-result") === target) target.innerHTML = `<p class="error">${esc(error.message)}</p>`;
      } finally {
        if (button.isConnected) button.disabled = false;
      }
    };
    if (ready.length >= 2) $("#compare-form").requestSubmit();
  } catch (error) { toast(error.message); }
}

function renderComparison(target, documentId, result) {
  const side = (item, version, label, index) => `<section class="change-side"><div class="eyebrow">${label} · v${version.number}${item ? ` · page ${item.page}` : ""}</div>${item ? `<p>${item.segments.map(s => s.changed ? `<mark class="diff-${label.toLowerCase()}">${esc(s.text)}</mark>` : esc(s.text)).join("")}</p><button class="text-button" data-change="${index}" data-side="${label.toLowerCase()}">View highlighted evidence ↗</button>` : '<p class="muted">No passage in this version.</p>'}</section>`;
  target.innerHTML = `<h3>${esc(result.title)}</h3><p class="comparison-direction">v${result.before.number} → v${result.after.number} <span class="pill">Works without AI</span></p><div class="change-stats"><span><strong>${result.counts.modified}</strong> Modified</span><span><strong>${result.counts.added}</strong> Added</span><span><strong>${result.counts.removed}</strong> Removed</span></div><p class="muted">${esc(result.notice)}</p>${result.total === 0 ? '<div class="empty"><h3>No text changes found</h3><p>These versions contain the same extracted passages. Visual or formatting changes may still exist.</p></div>' : result.changes.map((change, index) => `<article class="change-card"><span class="change-kind ${change.kind}">${esc(change.kind)}</span><div class="change-columns">${side(change.before, result.before, "Before", index)}${side(change.after, result.after, "After", index)}</div></article>`).join("")}${result.truncated ? '<p class="muted">Showing the first 200 changes. Split large documents to review the remaining changes.</p>' : ""}<button class="secondary" id="back-comparison-source">Back to source</button>`;
  target.querySelectorAll("[data-change]").forEach(button => button.onclick = () => {
    const label = button.dataset.side;
    const item = result.changes[Number(button.dataset.change)][label];
    viewDocument(documentId, result[label].id, item.page, item.text);
  });
  $("#back-comparison-source").onclick = () => viewDocument(documentId, result.after.id);
}
