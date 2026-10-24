"use strict";

async function conflictModal(selectedIds = []) {
  try {
    const documents = await api("/documents");
    modal(`<div class="eyebrow">CROSS-DOCUMENT REVIEW</div><h2>Find possible conflicts</h2><p class="muted">Check up to eight documents for different policy values or opposite permissions. Findings need your review: dates, departments and eligibility can explain a difference.</p><details><summary>What these checks cover</summary><p class="muted">Annual leave, remote-work days, expense deadlines, carryover, equipment allowances, retention periods, response times, and matched explicit permissions. Complex conditions, unrelated facts and ambiguous multi-value sentences need manual review.</p></details><form id="conflict-scan-form"><fieldset class="conflict-documents"><legend>Choose documents</legend>${documents.map(d => `<label><input type="checkbox" name="conflict-document" value="${d.id}" ${selectedIds.includes(d.id) ? "checked" : ""}> <span>${esc(d.title)} <small>v${d.version} · ${esc(d.status)}</small></span></label>`).join("") || '<p class="muted">Upload at least two documents first.</p>'}</fieldset><div class="toolbar"><button class="primary" type="submit">Check selected documents</button><button class="secondary" type="button" id="refresh-conflict-docs">Refresh documents</button>${user.role !== "viewer" ? '<button class="secondary" type="button" id="load-conflict-demo">Explore conflict review</button>' : ""}</div></form><div id="conflict-result" aria-live="polite"></div>`);
    $("#modal").classList.add("comparison-modal");
    const selection = () => Array.from(document.querySelectorAll('input[name="conflict-document"]:checked')).map(input => input.value);
    $("#refresh-conflict-docs").onclick = () => conflictModal(selection());
    if ($("#load-conflict-demo")) $("#load-conflict-demo").onclick = event => loadConflictDemo(event.target);
    $("#conflict-scan-form").onsubmit = async event => {
      event.preventDefault();
      const result = $("#conflict-result");
      const ids = selection();
      if (ids.length < 2 || ids.length > 8) { result.innerHTML = '<p class="error">Select between two and eight different documents.</p>'; return; }
      const button = event.target.querySelector('button[type="submit"]');
      button.disabled = true;
      result.innerHTML = '<p class="muted" role="status">Checking the current versions for possible conflicts…</p>';
      try {
        const data = await post("/conflicts/scan", {documents: ids});
        if ($("#conflict-result") !== result) return;
        if (selection().join("|") !== ids.join("|")) { result.innerHTML = '<p class="muted">The selection changed. Check the selected documents again.</p>'; return; }
        renderConflicts(result, data);
      } catch (error) { if ($("#conflict-result") === result) result.innerHTML = `<p class="error">${esc(error.message)}</p>`; }
      finally { if (button.isConnected) button.disabled = false; }
    };
    if (selectedIds.length >= 2 && selectedIds.every(id => documents.some(d => d.id === id && d.status === "ready"))) $("#conflict-scan-form").requestSubmit();
  } catch (error) { toast(error.message); }
}

function renderConflicts(target, result) {
  const source = (item, index, side) => `<section class="change-side"><div class="eyebrow">SOURCE ${side === 0 ? "A" : "B"} · v${item.version} · page ${item.page}</div><h4>${esc(item.title)}</h4><p class="muted">Uploaded ${esc(date(item.uploaded))}</p><span class="conflict-value">${esc(item.value)}</span><p>${esc(item.text)}</p><button class="text-button" data-conflict-evidence="${index}" data-source-side="${side}">View highlighted evidence ↗</button></section>`;
  target.innerHTML = `<div class="change-stats"><span><strong>${result.total}</strong> Possible conflicts</span><span><strong>${result.claims_checked}</strong> Checkable claims</span><span><strong>${result.documents.length}</strong> Documents</span></div><p class="muted">${esc(result.notice)}</p><p class="footer-note">Checks run locally. Your authoritative-source choices are saved for your personal review of these exact versions.</p>${result.findings.length ? '<label>Show<select id="conflict-filter"><option value="all">All findings</option><option value="open">Unreviewed</option><option value="authoritative">Authoritative source selected</option><option value="dismissed">Difference explained</option></select></label><div id="conflict-cards"></div>' : '<div class="empty"><h3>No possible conflicts found by these checks</h3><p>These checks cover supported policy quantities and explicit permissions. This does not establish that all statements agree.</p></div>'}${result.truncated ? '<p class="muted">Showing the first 100 findings. Select fewer documents to review remaining findings.</p>' : ""}`;
  if (!result.findings.length) return;
  const draw = () => {
    const filter = $("#conflict-filter").value;
    const visible = result.findings.map((finding, index) => ({finding, index})).filter(({finding}) => filter === "all" || finding.review.status === filter);
    $("#conflict-cards").innerHTML = visible.map(({finding, index}) => {
      const review = finding.review;
      const outcome = review.status === "authoritative" ? review.preferred_version : review.status;
      return `<article class="change-card"><div class="conflict-heading"><h3>${esc(finding.topic)}</h3><span class="pill">${review.status === "authoritative" ? "Your authority selected" : review.status === "dismissed" ? "Difference explained" : "Needs review"}</span></div><p class="muted">${esc(finding.sources[0].value)} vs ${esc(finding.sources[1].value)} · ${esc(finding.unit)}</p><div class="change-columns">${finding.sources.map((item, side) => source(item, index, side)).join("")}</div><ul class="conflict-warnings">${finding.warnings.map(warning => `<li>${esc(warning)}</li>`).join("")}</ul><form data-conflict-review="${index}"><label>Your review<select name="outcome"><option value="open" ${outcome === "open" ? "selected" : ""}>Keep unreviewed</option>${finding.sources.map((item, side) => `<option value="${item.version_id}" ${outcome === item.version_id ? "selected" : ""}>Source ${side === 0 ? "A" : "B"} is authoritative for my review</option>`).join("")}<option value="dismissed" ${outcome === "dismissed" ? "selected" : ""}>Difference explained by context</option></select></label><label>Reason or context (optional)<textarea name="note" rows="2" maxlength="1000" placeholder="For example, the newer policy applies to permanent employees.">${esc(review.note)}</textarea></label><button class="secondary" type="submit">Save my review</button><div class="review-status" role="status">${review.updated ? `Saved ${esc(date(review.updated))}` : ""}</div></form></article>`;
    }).join("") || '<p class="muted">No findings match this review filter.</p>';
    $("#conflict-cards").querySelectorAll("[data-conflict-evidence]").forEach(button => button.onclick = () => {
      const item = result.findings[Number(button.dataset.conflictEvidence)].sources[Number(button.dataset.sourceSide)];
      viewDocument(item.document, item.version_id, item.page, item.text, () => restoreConflictReview(result));
    });
    $("#conflict-cards").querySelectorAll("[data-conflict-review]").forEach(form => form.onsubmit = async event => {
      event.preventDefault();
      const finding = result.findings[Number(form.dataset.conflictReview)];
      const fields = new FormData(form), outcome = fields.get("outcome");
      const status = ["open", "dismissed"].includes(outcome) ? outcome : "authoritative";
      const button = form.querySelector("button");
      button.disabled = true;
      form.querySelector(".review-status").textContent = "Saving your review…";
      try {
        const saved = await post("/conflicts/review", {left_version: finding.sources[0].version_id, right_version: finding.sources[1].version_id, fingerprint: finding.id, status, preferred_version: status === "authoritative" ? outcome : null, note: fields.get("note")});
        finding.review = saved;
        if (form.isConnected) {
          form.querySelector(".review-status").textContent = "Saved for your review of these source versions.";
          form.closest("article").querySelector(".pill").textContent = status === "authoritative" ? "Your authority selected" : status === "dismissed" ? "Difference explained" : "Needs review";
        }
      } catch (error) { if (form.isConnected) form.querySelector(".review-status").textContent = error.message; }
      finally { if (button.isConnected) button.disabled = false; }
    });
  };
  $("#conflict-filter").onchange = draw;
  draw();
}

function restoreConflictReview(result) {
  modal('<div class="eyebrow">CROSS-DOCUMENT REVIEW</div><h2>Possible conflicts</h2><p class="muted">Reviewing the source versions from your last scan.</p><button class="secondary" id="rerun-conflict-scan">Run a new scan</button><div id="conflict-result" aria-live="polite"></div>');
  $("#modal").classList.add("comparison-modal");
  $("#rerun-conflict-scan").onclick = () => conflictModal(result.documents.map(document => document.document));
  renderConflicts($("#conflict-result"), result);
}

async function loadConflictDemo(button) {
  button.disabled = true;
  const ids = [];
  try {
    for (const year of [2025, 2026]) {
      const response = await fetch(`/static/demo/policy-${year}.pdf`);
      if (!response.ok) throw Error("The fictional sample file could not be loaded.");
      const form = new FormData();
      form.append("file", await response.blob(), `Conflict sample - Handbook ${year}.pdf`);
      form.append("visibility", "private");
      form.append("category", "People");
      const created = await api("/documents", {method: "POST", body: form});
      ids.push(created.id);
    }
    await navigate("documents");
    await conflictModal(ids);
    toast("Two fictional policy documents were uploaded privately. If still indexing, choose Refresh documents, then check them.");
  } catch (error) { toast(`${ids.length ? "A sample document was saved in your library. " : ""}${error.message}`); }
  finally { if (button.isConnected) button.disabled = false; }
}
