"use strict";

async function renderKnowledgeMap() {
  const data = await api("/knowledge-map");
  $("#content").innerHTML = head("Knowledge map", "Explore the evidence behind your answers.", '<button class="secondary" id="refresh-map">Refresh map</button>') +
    `<div class="stats">${stat("Documents", data.stats.documents, "Accessible in this view")}${stat("Source versions", data.stats.versions, "Saved evidence trail")}${stat("Your cited answers", data.stats.answers, "Linked to their sources")}${stat("Earlier versions cited", data.stats.earlier_version_answers, "Review the changes")}</div><p class="muted">${esc(data.notice)}</p>${data.limited ? '<p class="indexing-notice">This is a bounded view of recent documents and answers. Some older items are outside this map.</p>' : ""}` +
    (data.nodes.length ? `<div class="map-controls"><input id="map-search" aria-label="Search map" placeholder="Find a document or answer…"><label><input type="checkbox" id="map-historical"> Earlier-version citations only</label><button class="secondary" id="map-list-toggle">List view</button><button class="secondary" id="map-fit">Fit map</button><button class="secondary" id="map-focus">Focus connections</button><button class="secondary" id="map-zoom-out" aria-label="Zoom out">−</button><button class="secondary" id="map-zoom-in" aria-label="Zoom in">+</button></div><div class="map-legend"><span class="document">● Documents</span><span class="version">● Versions</span><span class="answer">● Your answers</span><span class="historical">● Earlier-version evidence</span></div><div class="knowledge-map-layout"><section class="map-board"><p class="footer-note">Drag a node to arrange it. Drag the background to pan. Use +/− or the mouse wheel to zoom. Select a node or a citation line to explore.</p><svg id="knowledge-canvas" viewBox="0 0 1000 650" role="group" aria-label="Interactive knowledge map"><defs><pattern id="map-grid" width="24" height="24" patternUnits="userSpaceOnUse"><circle cx="1" cy="1" r="1" fill="#ced8cd"/></pattern></defs><rect width="100%" height="100%" fill="url(#map-grid)"/><g id="map-scene"></g></svg><div id="map-list" class="hidden"></div><p id="map-status" class="footer-note" role="status"></p></section><aside id="map-inspector" class="map-inspector" aria-live="polite"></aside></div>` : empty("Your evidence map starts here", "Upload a document, then ask a question. Its saved citations will become real connections on this map.", '<button class="primary" data-upload>Upload a document</button>'));
  $("#refresh-map").onclick = () => navigate("map");
  if (!data.nodes.length) { bindActions(); return; }
  const svg = $("#knowledge-canvas"), scene = $("#map-scene");
  const nodes = data.nodes.map((node, index) => ({...node, index}));
  const byId = new Map(nodes.map(node => [node.id, node]));
  const edges = data.edges.map((edge, index) => ({...edge, index}));
  const state = {selected: null, edge: null, query: "", historical: false, list: false, scale: 1, x: 0, y: 0};
  const types = ["document", "version", "answer"];
  const height = Math.max(580, ...types.map(type => nodes.filter(node => node.type === type).length * 50));
  types.forEach((type, column) => {
    const items = nodes.filter(node => node.type === type);
    items.forEach((node, row) => { node.x = 150 + column * 340; node.y = 55 + (row + .5) * height / Math.max(1, items.length); });
  });
  const linkedIds = id => {
    const first = new Set([id, ...edges.filter(edge => edge.source === id || edge.target === id).map(edge => edge.source === id ? edge.target : edge.source)]);
    const trail = new Set(first);
    for (const edge of edges) if (first.has(edge.source) || first.has(edge.target)) { trail.add(edge.source); trail.add(edge.target); }
    return trail;
  };
  const visible = () => {
    if (!state.historical) return new Set(nodes.map(node => node.id));
    const ids = new Set();
    for (const edge of edges) if (edge.type === "citation" && edge.historical) { ids.add(edge.source); ids.add(edge.target); }
    for (const edge of edges) if (edge.type === "version" && ids.has(edge.target)) ids.add(edge.source);
    return ids;
  };
  const searchMatches = node => !state.query || (node.label + " " + (node.preview || "")).toLowerCase().includes(state.query);
  const transform = () => scene.setAttribute("transform", `translate(${state.x},${state.y}) scale(${state.scale})`);
  const fit = ids => {
    const selected = nodes.filter(node => ids.has(node.id));
    if (!selected.length) return;
    const minX = Math.min(...selected.map(n => n.x)) - 110, maxX = Math.max(...selected.map(n => n.x)) + 130;
    const minY = Math.min(...selected.map(n => n.y)) - 65, maxY = Math.max(...selected.map(n => n.y)) + 65;
    state.scale = Math.min(1.8, 960 / Math.max(250, maxX - minX), 610 / Math.max(200, maxY - minY));
    state.x = 500 - (minX + maxX) / 2 * state.scale;
    state.y = 325 - (minY + maxY) / 2 * state.scale;
    draw();
  };
  const zoom = (factor, center = {x: 500, y: 325}) => {
    const next = Math.max(.12, Math.min(4, state.scale * factor)), ratio = next / state.scale;
    state.x = center.x - (center.x - state.x) * ratio;
    state.y = center.y - (center.y - state.y) * ratio;
    state.scale = next;
    draw();
  };
  function draw() {
    const ids = visible(), neighbors = state.selected ? linkedIds(state.selected) : null;
    const relevant = node => searchMatches(node) && (!neighbors || neighbors.has(node.id));
    scene.innerHTML = edges.filter(edge => ids.has(edge.source) && ids.has(edge.target)).map(edge => {
      const a = byId.get(edge.source), b = byId.get(edge.target), middle = (a.x + b.x) / 2;
      const dim = (state.query && !searchMatches(a) && !searchMatches(b)) || (neighbors && (!neighbors.has(edge.source) || !neighbors.has(edge.target)));
      return `<path class="map-edge ${edge.type} ${edge.historical ? "historical" : ""} ${dim ? "dimmed" : ""} ${state.edge === edge.index ? "selected" : ""}" data-map-edge="${edge.index}" d="M${a.x},${a.y} C${middle},${a.y} ${middle},${b.y} ${b.x},${b.y}" fill="none" tabindex="0" role="button" aria-label="${esc(edge.type === "citation" ? `Citation from ${a.label} to ${b.label}` : `Saved version: ${b.label}`)}"><title>${esc(edge.type === "citation" ? `${a.label} → ${b.label}${edge.historical ? " · earlier version cited" : ""}` : b.label)}</title></path>`;
    }).join("") + nodes.filter(node => ids.has(node.id)).map(node => {
      const historical = node.type === "version" ? !node.current : node.historical;
      const label = Array.from(node.label).slice(0, 29).join("") + (Array.from(node.label).length > 29 ? "…" : "");
      return `<g class="map-node ${node.type} ${historical ? "historical" : ""} ${state.selected === node.id ? "selected" : ""} ${relevant(node) ? "" : "dimmed"}" data-map-node="${node.index}" transform="translate(${node.x},${node.y})" tabindex="0" role="button" aria-label="${esc(node.type + ": " + node.label + (historical ? ", earlier-version evidence" : ""))}"><title>${esc(node.label)}</title><circle class="map-hit" r="24"/><circle class="map-dot" r="${node.type === "version" ? 10 : 14}"/><text class="map-node-symbol" text-anchor="middle" dy="4">${node.type === "document" ? "D" : node.type === "version" ? node.version : "A"}</text><text class="map-node-label" x="21" dy="4">${esc(label)}</text></g>`;
    }).join("");
    transform();
    const shown = nodes.filter(node => ids.has(node.id) && searchMatches(node));
    $("#map-status").textContent = `${shown.length} matching nodes · ${Math.round(state.scale * 100)}% zoom${state.selected ? " · Connected evidence emphasized" : ""}${!ids.size ? " · No earlier-version citations in this view" : ""}`;
    $("#map-list").innerHTML = shown.map(node => `<button class="map-list-item ${state.selected === node.id ? "selected" : ""}" data-map-list-node="${node.index}"><span class="pill">${esc(node.type)}</span> ${esc(node.label)}${node.historical || (node.type === "version" && !node.current) ? ' <small>Earlier version</small>' : ""}</button>`).join("") || '<p class="muted">No nodes match these filters.</p>';
    $("#map-list").querySelectorAll("[data-map-list-node]").forEach(button => button.onclick = () => {
      const index = Number(button.dataset.mapListNode);
      selectNode(index);
      $("#map-list").querySelector(`[data-map-list-node="${index}"]`)?.focus({preventScroll: true});
    });
  }
  function evidenceButtons(connection) {
    return connection.evidence.map((item, index) => `<button class="secondary" data-map-evidence="${connection.index}" data-evidence-index="${index}">${item.text ? "Highlight" : "Open"} page ${item.page} ↗</button>`).join("");
  }
  function wireInspector() {
    const panel = $("#map-inspector");
    panel.querySelectorAll("[data-neighbor]").forEach(button => button.onclick = () => { selectNode(Number(button.dataset.neighbor)); fit(linkedIds(state.selected)); });
    panel.querySelectorAll("[data-map-evidence]").forEach(button => button.onclick = () => {
      const connection = edges[Number(button.dataset.mapEvidence)], quote = connection.evidence[Number(button.dataset.evidenceIndex)];
      viewDocument(connection.document, connection.version_id, quote.page, quote.text);
    });
  }
  function selectNode(index) {
    const node = nodes[index];
    state.selected = node.id; state.edge = null;
    const connections = edges.filter(edge => edge.source === node.id || edge.target === node.id);
    const prior = node.type === "version" && !node.current;
    const canCompare = node.status === "ready" && byId.get("version:" + node.current_version_id)?.status === "ready";
    $("#map-inspector").innerHTML = `<div class="eyebrow">${esc(node.type)}</div><h3>${esc(node.label)}</h3>${node.status ? `<span class="pill">${esc(node.status)}</span>` : ""}${node.created ? `<p class="muted">Saved ${esc(date(node.created))}</p>` : ""}${node.type === "answer" ? `<p class="map-answer-preview">${esc(node.preview)}</p><p class="muted">${node.model === "extractive" ? "Source excerpts" : "Saved answer"}</p>` : ""}${node.historical || prior ? '<p class="map-version-notice">This evidence includes an earlier document version. Compare the versions to check whether the relevant passage changed.</p>' : ""}<div class="toolbar"><button class="primary" id="map-open-node">${node.type === "answer" ? "Open conversation" : "Open source"}</button>${prior && node.current_version_id ? `<button class="secondary" id="map-compare-current" ${canCompare ? "" : "disabled"}>${canCompare ? "Compare with current" : "Wait for indexing to compare"}</button>` : ""}<button class="text-button" id="map-clear-selection">Clear selection</button></div><h4>Connections (${connections.length})</h4>${connections.map(connection => {
      const neighbor = byId.get(connection.source === node.id ? connection.target : connection.source);
      return `<div class="map-connection"><button class="text-button" data-neighbor="${neighbor.index}">${esc(neighbor.label)}</button><p class="muted">${connection.type === "citation" ? `Saved citation${connection.historical ? " · earlier version" : ""}` : "Belongs to document"}</p>${connection.type === "citation" ? evidenceButtons(connection) : ""}</div>`;
    }).join("") || '<p class="muted">No saved connections in the current view.</p>'}`;
    $("#map-open-node").onclick = async () => {
      if (node.type === "answer") {
        activeConversation = node.conversation;
        await navigate("chat");
        document.querySelector(`[data-message="${CSS.escape(node.message)}"]`)?.scrollIntoView({block: "center"});
      } else viewDocument(node.document, node.version_id || node.current_version_id);
    };
    if ($("#map-compare-current")) $("#map-compare-current").onclick = () => compareModal(node.document, node.version_id, node.current_version_id);
    $("#map-clear-selection").onclick = () => { state.selected = null; state.edge = null; draw(); intro(); };
    wireInspector(); draw();
  }
  function selectEdge(index) {
    const connection = edges[index];
    if (connection.type === "version") { selectNode(byId.get(connection.target).index); return; }
    state.selected = null; state.edge = index;
    $("#map-inspector").innerHTML = `<div class="eyebrow">SAVED CITATION</div><h3>${esc(byId.get(connection.source).label)}</h3><p>Supports: ${esc(byId.get(connection.target).label)}</p>${connection.historical ? '<p class="map-version-notice">This answer cites an earlier version. Review its supporting passage before treating it as current.</p>' : ""}${connection.evidence.map(item => `<p class="map-answer-preview">Page ${item.page}: ${esc(item.text.slice(0,700))}</p>`).join("")}${evidenceButtons(connection)}`;
    wireInspector(); draw();
  }
  function intro() { $("#map-inspector").innerHTML = '<div class="eyebrow">FOLLOW THE EVIDENCE</div><h3>Select a node or line</h3><p class="muted">Documents connect to their saved versions. Versions connect to the answers that cited them. Amber links mark earlier-version citations.</p><p class="muted">Use List view for a searchable, keyboard-friendly list of the same nodes.</p>'; }
  $("#map-search").oninput = event => { state.query = event.target.value.trim().toLowerCase(); draw(); };
  $("#map-historical").onchange = event => { state.historical = event.target.checked; state.selected = null; state.edge = null; intro(); fit(visible()); draw(); };
  $("#map-fit").onclick = () => fit(visible());
  $("#map-focus").onclick = () => {
    if (!state.selected) { toast("Select a node first to focus its connections."); return; }
    fit(new Set([...linkedIds(state.selected)].filter(id => visible().has(id))));
  };
  $("#map-zoom-in").onclick = () => zoom(1.25);
  $("#map-zoom-out").onclick = () => zoom(.8);
  $("#map-list-toggle").onclick = event => { state.list = !state.list; svg.classList.toggle("hidden", state.list); $("#map-list").classList.toggle("hidden", !state.list); event.target.textContent = state.list ? "Graph view" : "List view"; };
  const point = event => { const value = svg.createSVGPoint(); value.x = event.clientX; value.y = event.clientY; return value.matrixTransform(svg.getScreenCTM().inverse()); };
  let drag = null;
  svg.addEventListener("pointerdown", event => {
    if (event.button !== 0) return;
    const location = point(event), node = event.target.closest("[data-map-node]"), edge = event.target.closest("[data-map-edge]");
    drag = {index: node ? Number(node.dataset.mapNode) : null, edge: edge ? Number(edge.dataset.mapEdge) : null, start: location, x: state.x, y: state.y, moved: false};
    svg.setPointerCapture(event.pointerId);
  });
  svg.addEventListener("pointermove", event => {
    if (!drag) return;
    const location = point(event), dx = location.x - drag.start.x, dy = location.y - drag.start.y;
    if (Math.abs(dx) + Math.abs(dy) > 4) drag.moved = true;
    if (!drag.moved) return;
    if (drag.index !== null) { nodes[drag.index].x = (location.x - state.x) / state.scale; nodes[drag.index].y = (location.y - state.y) / state.scale; draw(); }
    else { state.x = drag.x + dx; state.y = drag.y + dy; transform(); }
  });
  svg.addEventListener("pointerup", event => {
    if (!drag) return;
    const previous = drag; drag = null;
    svg.releasePointerCapture(event.pointerId);
    if (previous.moved) return;
    if (previous.index !== null) selectNode(previous.index);
    else if (previous.edge !== null) selectEdge(previous.edge);
  });
  svg.addEventListener("pointercancel", () => { drag = null; });
  svg.addEventListener("keydown", event => {
    if (!["Enter", " "].includes(event.key)) return;
    const node = event.target.closest("[data-map-node]"), edge = event.target.closest("[data-map-edge]");
    if (!node && !edge) return;
    event.preventDefault();
    const selector = node ? `[data-map-node="${node.dataset.mapNode}"]` : `[data-map-edge="${edge.dataset.mapEdge}"]`;
    if (node) selectNode(Number(node.dataset.mapNode)); else selectEdge(Number(edge.dataset.mapEdge));
    scene.querySelector(selector)?.focus({preventScroll: true});
  });
  svg.addEventListener("wheel", event => { event.preventDefault(); zoom(event.deltaY < 0 ? 1.12 : .89, point(event)); }, {passive: false});
  intro(); fit(visible());
}
