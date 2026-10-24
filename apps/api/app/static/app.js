function visualFile(name) { return /\.(pdf|png|jpe?g|webp)$/i.test(name); }
"use strict";
const $ = (s) => document.querySelector(s);
const esc = (s) =>
  String(s ?? "").replace(
    /[&<>"']/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        c
      ],
  );
let user = null,
  page = "overview",
  registering = true,
  docs = [],
  conversations = [],
  activeConversation = null,
  busy = false,
  toastTimer,
  pollTimer,
  streamController;
let neonAuthClient = null;
async function api(path, options = {}) {
  const r = await fetch("/api/v1" + path, {
    credentials: "same-origin",
    ...options,
    headers:
      options.body instanceof FormData
        ? {}
        : { "Content-Type": "application/json", ...options.headers },
  });
  let data;
  try {
    data = await r.json();
  } catch {
    data = {
      detail: await Promise.resolve(
        r.status === 429
          ? "Too many requests. Please wait a minute."
          : "Request failed.",
      ),
    };
  }
  if (!r.ok) {
    if (r.status === 401 && user) {
      user = null;
      showAuth();
    }
    throw Error(
      typeof data.detail === "string"
        ? data.detail
        : "Please check the form fields.",
    );
  }
  return data;
}
const post = (path, data = {}) =>
  api(path, { method: "POST", body: JSON.stringify(data) });
function toast(text) {
  $("#toast").textContent = text;
  $("#toast").classList.remove("hidden");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => $("#toast").classList.add("hidden"), 4200);
}
function date(value) {
  return new Date(value).toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}
function modal(html) {
  $("#modal").classList.remove("comparison-modal");
  $("#modal-content").innerHTML = html;
  $("#modal").showModal();
}
$("#close-modal").onclick = () => $("#modal").close();
function showAuth() {
  $("#auth").classList.remove("hidden");
  $("#app").classList.add("hidden");
  clearInterval(pollTimer);
}
$("#auth-toggle").onclick = () => {
  registering = !registering;
  $(".register-fields").classList.toggle("hidden", !registering);
  $("#auth-title").textContent = registering
    ? "Build your knowledge workspace"
    : "Welcome back to your workspace";
  $("#auth-submit").textContent = registering
    ? "Create workspace ↗"
    : "Sign in ↗";
  $("#auth-toggle").textContent = registering ? "Sign in" : "Create an account";
  $("#auth-error").textContent = "";
  $("#auth-form [name=password]").autocomplete = registering
    ? "new-password"
    : "current-password";
};
$("#auth-form").onsubmit = async (e) => {
  e.preventDefault();
  const form = Object.fromEntries(new FormData(e.target));
  $("#auth-submit").disabled = true;
  $("#auth-error").textContent = "";
  try {
    if (neonAuthClient) {
      const result = registering
        ? await neonAuthClient.signUp.email({ email: form.email, password: form.password, name: form.name })
        : await neonAuthClient.signIn.email({ email: form.email, password: form.password });
      if (result.error) throw Error(result.error.message || "Neon sign-in failed.");
      const token = await neonAuthClient.token();
      if (token.error || !token.data?.token) throw Error("Complete Neon email verification, then sign in.");
      await post("/auth/neon", { token: token.data.token, workspace: form.workspace || "My knowledge workspace" });
    } else {
      await post("/auth/" + (registering ? "register" : "login"), form);
    }
    await start();
  } catch (err) {
    $("#auth-error").textContent = err.message;
  } finally {
    $("#auth-submit").disabled = false;
  }
};
$("#logout").onclick = async () => {
  try {
    await post("/auth/logout");
    if (neonAuthClient) await neonAuthClient.signOut();
    user = null;
    activeConversation = null;
    showAuth();
  } catch (e) {
    toast(e.message);
  }
};
$("#navigation").onclick = (e) => {
  const button = e.target.closest("[data-page]");
  if (button) navigate(button.dataset.page);
};
function head(title, subtitle, action = "") {
  return `<div class="page-head"><div><h1>${title}</h1><p>${subtitle}</p></div>${action}</div>`;
}
const empty = (title, text, button = "") =>
  `<div class="empty"><div class="empty-symbol">✧</div><h3>${title}</h3><p>${text}</p>${button}</div>`;
function bindActions() {
  document.querySelectorAll("[data-retry]").forEach(
    (b) =>
      (b.onclick = async () => {
        try {
          await post("/documents/" + b.dataset.retry + "/retry");
          toast("Queued for retry");
          await navigate("documents");
        } catch (e) {
          toast(e.message);
        }
      }),
  );
  document
    .querySelectorAll("[data-go]")
    .forEach((b) => (b.onclick = () => navigate(b.dataset.go)));
  document.querySelectorAll("[data-ask]").forEach(
    (b) =>
      (b.onclick = async () => {
        activeConversation = null;
        await navigate("chat");
        $("#question").value = b.dataset.ask;
        $("#question").focus();
      }),
  );
  document
    .querySelectorAll("[data-source]")
    .forEach(
      (b) =>
        (b.onclick = () =>
          viewDocument(
            b.dataset.source,
            b.dataset.version,
            b.dataset.sourcePage,
            b.dataset.evidence,
          )),
    );
  document.querySelectorAll("[data-conflicts]").forEach(b => b.onclick = () => conflictModal());
  document.querySelectorAll("[data-comparison-demo]").forEach(b => b.onclick = () => loadComparisonDemo(b));
  document.querySelectorAll("[data-compare-doc]").forEach(b => b.onclick = () => compareModal(b.dataset.compareDoc));
  document
    .querySelectorAll("[data-upload]")
    .forEach((b) => (b.onclick = uploadModal));
  document
    .querySelectorAll("[data-seed]")
    .forEach((b) => {
      b.classList.toggle("hidden", Boolean(user?.demo));
      b.onclick = seedDemo;
    });
}
async function start() {
  user = await api("/users/me");
  $("#auth").classList.add("hidden");
  $("#app").classList.remove("hidden");
  $("#workspace-name").textContent = user.workspace;
  $("#workspace-initial").textContent = user.workspace[0].toUpperCase();
  $("#user-name").textContent = user.name;
  $("#user-avatar").textContent = user.name[0].toUpperCase();
  $("#user-role").textContent = user.role;
  $("[data-page=settings]").classList.toggle("hidden", Boolean(user.demo));
  $("#mode-label").textContent = user.provider === "gemini" ? "Gemini / " + user.mode : user.mode;
  await navigate(page);
  clearInterval(pollTimer);
  pollTimer = setInterval(async () => {
    if (!user || !docs.some((d) => d.status === "processing")) return;
    try {
      docs = await api("/documents");
      if (page === "documents") renderDocuments();
      if (page === "chat") updateIndexingNotice();
      $("#doc-count").textContent = docs.length;
    } catch {}
  }, 2500);
}
async function navigate(next) {
  if (busy) {
    toast("Cancel the current answer before leaving this conversation.");
    return;
  }
  page = next;
  $("#breadcrumb").textContent = {
    overview: "Overview",
    chat: "Ask Knowra",
    documents: "Knowledge library",
    search: "Search",
    analytics: "Insights",
    map: "Knowledge map",
    settings: "Workspace settings",
  }[page];
  document
    .querySelectorAll("nav button")
    .forEach((b) => b.classList.toggle("active", b.dataset.page === page));
  $("#content").innerHTML =
    '<div class="loading">Gathering your workspace…</div>';
  try {
    docs = await api("/documents");
    $("#doc-count").textContent = docs.length;
    await {
      overview: renderOverview,
      documents: renderDocuments,
      chat: renderChat,
      search: renderSearch,
      analytics: renderAnalytics,
      map: renderKnowledgeMap,
      settings: renderSettings,
    }[page]();
  } catch (err) {
    $("#content").innerHTML = empty(
      "Something needs attention",
      esc(err.message),
    );
  }
}
function stat(label, value, caption) {
  return `<div class="stat"><div class="stat-label">${label}</div><div class="stat-value">${value}</div><div class="stat-caption">${caption}</div></div>`;
}
function docRow(d) {
  return `<div class="document-row"><span class="file-icon">▤</span><div><button class="link-button" data-source="${d.id}">${esc(d.title)}</button><small>${esc(d.category)} · ${date(d.created)}</small></div><span class="status ${d.status}">${esc(d.status)}</span></div>`;
}
async function renderOverview() {
  const a = await api("/analytics");
  const greet =
    new Date().getHours() < 12
      ? "Good morning"
      : new Date().getHours() < 18
        ? "Good afternoon"
        : "Good evening";
  $("#content").innerHTML =
    head(
      `${greet}, ${esc(user.name.split(" ")[0])} <span class="muted">✳</span>`,
      "Here's what's happening in your knowledge workspace.",
      `<span class="date-chip">${new Date().toLocaleDateString(undefined, { weekday: "long", month: "long", day: "numeric" })}</span>`,
    ) +
    `<section class="hero"><div><div class="eyebrow">LESS SEARCHING. MORE KNOWING.</div><h2>Your team's knowledge.<br>A little more connected.</h2><p>Turn scattered documents into answers you can trust.<br>Every answer starts with a source.</p><button class="primary" data-go="chat">Ask your first question <span>↗</span></button></div><div class="hero-art">✳</div></section><div class="stats">${stat("Knowledge library", a.documents, "Documents in your workspace")}${stat("Ready to explore", a.ready, "Indexed and searchable")}${stat("Questions answered", a.questions, "Your conversations, remembered")}${stat("Helpful answers", a.positive || 0, "Based on your feedback")}</div><div class="grid-two"><section class="panel"><div class="section-head"><h3>Your knowledge, at a glance</h3><button class="text-button" data-go="documents">View library ↗</button></div>${docs.length ? docs.slice(0, 4).map(docRow).join("") : empty("A fresh start for your knowledge", "Upload a document or explore with fictional sample data.", `<button class="secondary" data-seed>Explore sample workspace ↗</button>`)}</section><section class="panel"><div class="section-head"><h3>A good place to start</h3><span class="pill">✧ Ask Knowra</span></div><p class="muted">Let your documents do the talking.</p>${["Compare the 2025 and 2026 leave policies", "How does customer onboarding work?", "What are our security requirements?"].map((q) => `<button class="prompt" data-ask="${q}">${q}<span>↗</span></button>`).join("")}<div class="footer-note">Grounded in your documents. Linked to the source.</div></section></div><div class="footer-note">◇ Your knowledge stays within your workspace · ${esc(user.mode)} mode</div>`;
  bindActions();
}
async function seedDemo() {
  try {
    const result = await post("/demo/seed");
    toast(
      result.created
        ? "Four fictional sample documents added."
        : "Sample documents are already in your library.",
    );
    await navigate(page);
  } catch (e) {
    toast(e.message);
  }
}
function renderDocuments() {
  const prior = $("#doc-filter")?.value || "";
  $("#content").innerHTML =
    head(
      "Knowledge library",
      "A shared home for everything your team knows.",
      user.role === "viewer"
        ? ""
        : `<button class="primary" data-upload>+ Upload document</button>`,
    ) +
    `<div class="toolbar"><input id="doc-filter" aria-label="Filter documents" placeholder="⌕  Find a document…" value="${esc(prior)}"><select id="category-filter" aria-label="Category"><option value="">All categories</option>${[...new Set(docs.map((d) => d.category))].map((c) => `<option>${esc(c)}</option>`).join("")}</select><button class="secondary" data-conflicts>Find possible conflicts</button><button class="secondary" data-seed>Load sample data</button>${user.role !== "viewer" ? '<button class="secondary" data-comparison-demo>Try comparison demo</button>' : ""}</div><div id="document-table"></div><p class="footer-note">PDF, PNG, JPEG, WebP, TXT, Markdown & CSV · Up to 10 MB per file · Private or shared with your workspace</p>`;
  const draw = () => {
    const q = $("#doc-filter").value.toLowerCase(),
      cat = $("#category-filter").value;
    const filtered = docs.filter(
      (d) => d.title.toLowerCase().includes(q) && (!cat || d.category === cat),
    );
    $("#document-table").innerHTML = filtered.length
      ? `<div class="table-wrap"><table><thead><tr><th>Document</th><th>Category</th><th>Access</th><th>Status</th><th>Added</th><th></th></tr></thead><tbody>${filtered.map((d) => `<tr><td><button class="link-button" data-source="${d.id}">▤ &nbsp;${esc(d.title)}</button>${d.error ? `<div class="error">${esc(d.error)}</div>` : ""}${d.status === "failed" ? `<button class="text-button" data-retry="${d.id}">Retry indexing</button>` : ""}</td><td>${esc(d.category)}</td><td>${esc(d.visibility)}</td><td><span class="status ${d.status}">${d.status}</span></td><td>${date(d.created)} · v${d.version}${d.version > 1 ? `<br><button class="text-button" data-compare-doc="${d.id}">Compare versions</button>` : ""}</td><td>${user.role === "viewer" ? "" : `<button class="delete" data-delete="${d.id}">Delete</button>`}</td></tr>`).join("")}</tbody></table></div>`
      : empty(
          docs.length ? "No matching documents" : "Your library starts here",
          docs.length
            ? "Try another search or category."
            : "Upload policies, guides, or playbooks to start finding answers.",
        );
    document.querySelectorAll("[data-delete]").forEach(
      (b) =>
        (b.onclick = () => {
          modal(
            `<h2>Delete this document?</h2><p>Its indexed passages will be removed from future searches. Previous conversation text remains in your history.</p><button id="confirm-delete" class="primary">Delete document</button>`,
          );
          $("#confirm-delete").onclick = async () => {
            try {
              await api("/documents/" + b.dataset.delete, { method: "DELETE" });
              $("#modal").close();
              await navigate("documents");
              toast("Document deleted");
            } catch (e) {
              toast(e.message);
            }
          };
        }),
    );
    bindActions();
  };
  $("#doc-filter").oninput = draw;
  $("#category-filter").onchange = draw;
  draw();
  bindActions();
}
function uploadModal() {
  modal(
    `<h2>Add to your knowledge</h2><p class="muted">Give your next answer a reliable source.</p><form id="upload-form"><label class="upload-zone">Choose a document or image<input type="file" name="file" accept=".pdf,.png,.jpg,.jpeg,.webp,.txt,.md,.csv" required></label><label>Category<select name="category"><option>General</option><option>People</option><option>Security</option><option>Operations</option><option>Product</option><option>Finance</option></select></label><label>Who can access this?<select name="visibility"><option value="workspace">Everyone in this workspace</option><option value="private">Only me</option></select></label><p class="muted">PDF (including scans), PNG, JPEG, WebP, TXT, Markdown, CSV · Maximum 10 MB</p><div id="upload-error" class="error"></div><button class="primary" type="submit">Upload & index ↗</button></form>`,
  );
  $("#upload-form").onsubmit = async (e) => {
    e.preventDefault();
    const button = e.target.querySelector("button");
    button.disabled = true;
    try {
      await api("/documents", { method: "POST", body: new FormData(e.target) });
      $("#modal").close();
      await navigate("documents");
      toast("Document uploaded and queued for indexing.");
    } catch (err) {
      $("#upload-error").textContent = err.message;
      button.disabled = false;
    }
  };
}
function sourcePageHTML(text, i, version, id, selected) {
  const meta = (version.layout_meta || [])[i];
  const tables = (meta?.tables || []).map(rows => `<div class="table-scroll"><table>${rows.map((row, n) => `<tr>${row.map(cell => n === 0 ? `<th>${esc(cell || "")}</th>` : `<td>${esc(cell || "")}</td>`).join("")}</tr>`).join("")}</table></div>`).join("");
  const preview = visualFile(selected.filename) ? `<details><summary>View original page</summary><img loading="lazy" style="width:100%;height:auto" alt="Original page ${i+1}" src="/api/v1/documents/${id}/versions/${selected.id}/pages/${i+1}/image"></details>` : "";
  return `<section id="source-page-${i+1}"><strong>Page ${i+1}${meta ? ` / ${esc(meta.method)}` : ""}</strong>${(meta?.warnings || []).map(w => `<p class="muted">${esc(w)}</p>`).join("")}${tables}<p class="extracted-page-text">${esc(text)}</p>${preview}</section>`;
}
async function viewDocument(id, selectedVersion, sourcePage, evidence, returnToReview) {
  try {
    const [d, versions] = await Promise.all([
      api("/documents/" + id),
      api("/documents/" + id + "/versions"),
    ]);
    const selected =
      versions.find((v) => v.id === selectedVersion) || versions[0];
    if (!selected) throw Error("No source version is available.");
    const version = await api("/documents/" + id + "/versions/" + selected.id);
    const editable =
      user.role !== "viewer" &&
      (d.owner === user.id || ["owner", "admin"].includes(user.role));
    modal(
      `<div class="eyebrow">SOURCE DOCUMENT · ${esc(d.category)}</div><h2>${esc(d.title)}</h2><div class="toolbar">${returnToReview ? '<button class="secondary" id="return-to-review">Back to review</button>' : ""}<select id="source-version" aria-label="Source version">${versions.map((v) => `<option value="${v.id}" ${v.id === selected.id ? "selected" : ""}>Version ${v.number} · ${esc(v.status)}</option>`).join("")}</select>${user.role === "owner" || user.role === "admin" ? '<button class="secondary" id="reindex-source">Reindex for search</button>' : ""}${versions.length > 1 ? `<button class="secondary" id="compare-source">Compare versions</button>` : ""}<a class="secondary" href="/api/v1/documents/${id}/versions/${selected.id}/original" target="_blank" rel="noopener">Open original ↗</a></div><span class="pill">${esc(d.visibility)} · SHA-256 ${esc(version.checksum.slice(0, 16))}…</span><div id="evidence-panel" data-source-key="${id}/${selected.id}"></div><div class="source-text">${version.pages.map((text, i) => sourcePageHTML(text, i, version, id, selected)).join("")}</div>${editable ? `<details><summary>Add a new version</summary><p class="muted">Previous versions and citations remain available.</p><form id="version-form"><input aria-label="New document version" type="file" name="file" accept=".pdf,.png,.jpg,.jpeg,.webp,.txt,.md,.csv" required><button class="primary">Upload version</button><div id="version-error" class="error"></div></form></details>` : ""}`,
    );
    if ($("#return-to-review")) $("#return-to-review").onclick = returnToReview;
    if ($("#compare-source")) $("#compare-source").onclick = () => compareModal(id);
    if (user.source_integrity) {
      const button = document.createElement("button");
      button.className = "secondary";
      button.textContent = "Verify original";
      button.onclick = async () => {
        button.disabled = true;
        try {
          const result = await api(`/documents/${id}/versions/${selected.id}/integrity`);
          toast(result.verified ? "Original verified: its checksum matches this source version." : "The original could not be verified. Check the source.");
        } catch (error) { toast(error.message); }
        finally { button.disabled = false; }
      };
      $("#modal-content .toolbar").append(button);
    }
    if (evidence && sourcePage) showEvidence(id, selected.id, Number(sourcePage), evidence, version.pages[Number(sourcePage)-1]);
    if ($("#reindex-source"))
      $("#reindex-source").onclick = async () => {
        try {
          await post("/documents/" + id + "/reindex");
          $("#modal").close();
          await navigate("documents");
          toast("Document queued for search reindexing");
        } catch (error) {
          toast(error.message);
        }
      };
    $("#source-version").onchange = (e) => {
      const value = e.target.value;
      $("#modal").close();
      viewDocument(id, value, null, null, returnToReview);
    };
    if (sourcePage)
      $("#source-page-" + sourcePage)?.scrollIntoView({ block: "start" });
    if (editable)
      $("#version-form").onsubmit = async (e) => {
        e.preventDefault();
        const button = e.target.querySelector("button");
        button.disabled = true;
        try {
          await api("/documents/" + id + "/versions", {
            method: "POST",
            body: new FormData(e.target),
          });
          $("#modal").close();
          await navigate("documents");
          toast("New version queued. Previous citations are preserved.");
        } catch (error) {
          $("#version-error").textContent = error.message;
          button.disabled = false;
        }
      };
  } catch (e) {
    toast(e.message);
  }
}
async function renderChat() {
  conversations = await api("/conversations");
  $("#content").innerHTML =
    head(
      "Ask Knowra",
      "A thoughtful answer starts with the right evidence.",
      `<span class="pill">${user.provider === "gemini" ? "Gemini / " : ""}${esc(user.mode)}</span>`,
    ) +
    `<div class="chat-layout"><aside class="conversation-list"><button id="new-chat" class="primary">+ New conversation</button>${conversations.map((c) => `<button class="conversation-button ${c.id === activeConversation ? "selected" : ""}" data-conversation="${c.id}">${esc(c.title)}</button>`).join("")}</aside><section class="chat-main"><div id="indexing-notice" class="indexing-notice hidden" role="status"></div><div class="messages" id="messages"></div><button class="secondary" id="chat-upload" type="button">+ Upload image or document</button><details class="visual-options"><summary>Ask about a diagram or table visually</summary><p class="muted">Optional: sends one selected page image to your configured AI provider. OCR and ordinary questions stay local until text synthesis.</p><label><input id="visual-enabled" type="checkbox"> Use a page image for this question</label><label>PDF or image<select id="visual-document"><option value="">Choose a ready PDF or image</option>${docs.filter(d => d.status === "ready" && visualFile(d.title)).map(d => `<option value="${d.id}">${esc(d.title)}</option>`).join("")}</select></label><label>Page<input id="visual-page" type="number" min="1" max="300" value="1"></label></details><form class="composer" id="chat-form"><textarea id="question" aria-label="Your question" placeholder="What would you like to know?" maxlength="3000" required rows="2"></textarea><button class="secondary hidden" id="cancel-answer" type="button">Cancel</button><button class="primary" id="send-question" type="submit" aria-label="Send question">↗</button></form><div class="composer-note">${user.mode === "Evidence only" ? "Evidence-only mode returns source passages. Configure an AI key on the server for synthesis." : "AI answers may contain mistakes. Check the linked source documents."}</div></section></div>`;
  $("#chat-upload").onclick = uploadModal;
  $("#chat-upload").classList.toggle("hidden", Boolean(user.demo));
  $("#new-chat").onclick = () => {
    if (busy) return;
    activeConversation = null;
    renderChat();
  };
  document.querySelectorAll("[data-conversation]").forEach(
    (b) =>
      (b.onclick = () => {
        if (busy) return;
        activeConversation = b.dataset.conversation;
        renderChat();
      }),
  );
  if (activeConversation) {
    const history = await api(
      "/conversations/" + activeConversation + "/messages",
    );
    $("#messages").innerHTML = history.map(messageHTML).join("");
    bindMessageActions();
    scrollMessages();
  } else {
    $("#messages").innerHTML = empty(
      "Your knowledge has answers.",
      "Ask a question, compare policies, or uncover the details.",
      `<button class="prompt" id="chat-example">How did our annual leave policy change?</button>`,
    );
    $("#chat-example").onclick = () => {
      $("#question").value = "Compare the 2025 and 2026 annual leave policies";
      $("#question").focus();
    };
  }
  updateIndexingNotice();
  $("#chat-form").onsubmit = sendQuestion;
  $("#question").onkeydown = (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      $("#chat-form").requestSubmit();
    }
  };
}
function updateIndexingNotice() {
  const visualSelect = $("#visual-document");
  if (visualSelect) {
    const ready = docs.filter(d => d.status === "ready" && visualFile(d.title));
    const signature = ready.map(d => d.id + d.title).join("|");
    if (visualSelect.dataset.ready !== signature) {
      const selected = visualSelect.value;
      visualSelect.innerHTML = `<option value="">Choose a ready PDF or image</option>${ready.map(d => `<option value="${d.id}">${esc(d.title)}</option>`).join("")}`;
      if (ready.some(d => d.id === selected)) visualSelect.value = selected;
      visualSelect.dataset.ready = signature;
    }
  }
  const notice = $("#indexing-notice");
  if (!notice) return;
  const pending = docs.filter(d => d.status === "processing").length;
  notice.classList.toggle("hidden", pending === 0);
  notice.textContent = pending ? `${pending} document(s) are being prepared. Wait for Ready in the Knowledge library before asking about them.` : "";
}
function messageHTML(m) {
  return `<article class="message ${m.role}" data-message="${esc(m.id || "")}"><div class="message-label">${m.role === "user" ? "You" : m.model === "extractive" ? "Source excerpts" : "✧ Knowra"}</div><div class="message-body">${esc(m.content)}</div>${m.citations?.length ? `<div class="sources">${m.citations.map((s, i) => `<button class="source-chip" data-source="${s.document}" data-version="${s.version_id || ""}" data-source-page="${s.page}" data-evidence="${esc((s.content || "").slice(0,4000))}">[${s.citation_number || i + 1}] ${esc(s.title)} · v${s.version || 1} · p.${s.page}</button>`).join("")}</div>` : ""}${m.role === "assistant" ? `<div class="feedback"><button data-feedback="${m.id}" data-value="1">${m.feedback === 1 ? "✓ Helpful" : "Helpful"}</button><button data-feedback="${m.id}" data-value="-1">${m.feedback === -1 ? "✓ Saved" : "Needs improvement"}</button></div>` : ""}</article>`;
}
function bindMessageActions() {
  bindActions();
  document.querySelectorAll("[data-feedback]").forEach(
    (b) =>
      (b.onclick = async () => {
        try {
          await post("/messages/" + b.dataset.feedback + "/feedback", {
            value: Number(b.dataset.value),
          });
          toast("Feedback saved");
        } catch (e) {
          toast(e.message);
        }
      }),
  );
}
function scrollMessages() {
  const box = $("#messages");
  box.scrollTop = box.scrollHeight;
}
async function sendQuestion(e) {
  e.preventDefault();
  if ($("#visual-enabled")?.checked && !$("#visual-document").value) { toast("Choose a ready PDF or image for visual analysis."); return; }
  if (busy) return;
  const text = $("#question").value.trim();
  if (!text) return;
  busy = true;
  streamController = new AbortController();
  $("#send-question").disabled = true;
  $("#question").disabled = true;
  $("#cancel-answer").classList.remove("hidden");
  $("#cancel-answer").onclick = () => streamController.abort();
  let completed = false;
  try {
    if (!activeConversation) {
      activeConversation = (await post("/conversations")).id;
      $("#messages").innerHTML = "";
    }
    $("#messages").insertAdjacentHTML(
      "beforeend",
      messageHTML({ role: "user", content: text }) +
        '<article class="message" id="stream-answer"><div class="message-label">✧ Knowra · Finding evidence…</div><div class="message-body"></div><div class="sources"></div></article>',
    );
    scrollMessages();
    const response = await fetch(
      "/api/v1/conversations/" + activeConversation + "/stream",
      {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ content: text, ...($("#visual-enabled")?.checked ? { visual_document_id: $("#visual-document").value, visual_page: Number($("#visual-page").value) } : {}) }),
        signal: streamController.signal,
      },
    );
    if (!response.ok) {
      let error;
      try {
        error = await response.json();
      } catch {}
      throw Error(
        error?.detail || "The answer could not be started. Please retry.",
      );
    }
    const reader = response.body.getReader(),
      decoder = new TextDecoder();
    let buffer = "";
    while (true) {
      const { value, done } = await reader.read();
      buffer += decoder.decode(value || new Uint8Array(), { stream: !done });
      let boundary;
      while ((boundary = buffer.indexOf("\n\n")) >= 0) {
        const block = buffer.slice(0, boundary);
        buffer = buffer.slice(boundary + 2);
        for (const line of block.split("\n")) {
          if (!line.startsWith("data: ")) continue;
          const event = JSON.parse(line.slice(6));
          if (event.type === "delta") {
            const body = $("#stream-answer .message-body");
            body.append(document.createTextNode(event.text));
            $("#stream-answer .message-label").textContent =
              "✧ Knowra · Answering";
            scrollMessages();
          }
          if (event.type === "citations") {
            $("#stream-answer .message-label").textContent = event.citations.length ? "Sources found - generating answer..." : "Checking available evidence...";
            $("#stream-answer .sources").innerHTML = event.citations
              .map(
                (source, i) =>
                  `<button class="source-chip" data-source="${source.document}" data-version="${source.version_id || ""}" data-source-page="${source.page}" data-evidence="${esc((source.content || "").slice(0,4000))}">[${source.citation_number || i + 1}] ${esc(source.title)} · v${source.version || 1} · p.${source.page}</button>`,
              )
              .join("");
            bindActions();
          }
          if (event.type === "error") throw Error(event.message);
          if (event.type === "done") completed = true;
        }
      }
      if (done) break;
    }
    if (!completed) throw Error("The answer was interrupted. Please retry.");
    await renderChat();
  } catch (error) {
    const label = $("#stream-answer .message-label");
    if (label)
      label.textContent =
        error.name === "AbortError"
          ? "✧ Answer canceled · Not saved"
          : "✧ Answer interrupted · Not saved";
    toast(error.name === "AbortError" ? "Answer canceled." : error.message);
    if ($("#question")) $("#question").value = text;
  } finally {
    busy = false;
    streamController = null;
    if ($("#send-question")) $("#send-question").disabled = false;
    if ($("#question")) $("#question").disabled = false;
    $("#cancel-answer")?.classList.add("hidden");
  }
}
function renderSearch() {
  $("#content").innerHTML =
    head(
      "Find the source",
      "Search the knowledge you can access, down to the passage.",
    ) +
    `<form class="toolbar" id="search-form"><input id="search-query" aria-label="Search knowledge" placeholder="Search policies, processes, details…" required maxlength="3000"><button class="primary">Search ↗</button></form><div id="search-results">${empty("A shortcut to the right passage", "Search by a topic, phrase, or question.")}</div>`;
  $("#search-form").onsubmit = async (e) => {
    e.preventDefault();
    try {
      const results = await post("/search", {
        content: $("#search-query").value,
      });
      $("#search-results").innerHTML = results.length
        ? results
            .map(
              (r, i) =>
                `<article class="search-result"><div class="section-head"><button class="link-button" data-source="${r.document}">${esc(r.title)}</button><span class="pill">Page ${r.page}</span></div><p>${esc(r.content)}</p><small class="muted">Match ${i + 1} · relevance ${r.score}</small></article>`,
            )
            .join("")
        : empty(
            "No supporting passages found",
            "Try a different phrase or add a relevant document.",
          );
      bindActions();
    } catch (err) {
      toast(err.message);
    }
  };
}
async function renderAnalytics() {
  const a = await api("/analytics");
  $("#content").innerHTML =
    head(
      "Workspace insights",
      "A clear view of your knowledge and your conversations.",
    ) +
    `<div class="stats">${stat("Accessible documents", a.documents, "Visible to your account")}${stat("Your questions", a.questions, "Saved assistant answers")}${stat("Average response time", (a.latency / 1000).toFixed(2) + "s", "Measured end-to-end")}${stat("Marked helpful", a.positive || 0, "Your answer feedback")}</div><div class="grid-two"><section class="panel"><h3>Knowledge readiness</h3><div class="insight-bar"><span></span></div><p>${a.ready} of ${a.documents} accessible documents indexed</p><p class="muted">${docs.filter((d) => d.status === "processing").length} processing · ${docs.filter((d) => d.status === "failed").length} need attention</p></section><section class="panel"><div class="eyebrow">ANSWER ENGINE</div><h2>${esc(user.mode)}</h2><p class="muted">${esc(user.retrieval)} retrieval with versioned page-level source references. ${user.mode === "Evidence only" ? "No AI provider is configured. Answers show original source passages." : "The configured AI model synthesizes retrieved evidence."}</p><p class="footer-note">${a.tokens || 0} provider-reported tokens · Costs and quality are not estimated.</p></section></div>`;
}
async function renderSettings() {
  const isAdmin = ["owner", "admin"].includes(user.role);
  $("#content").innerHTML =
    head(
      "Workspace settings",
      "Manage your account, your team, and access to your knowledge.",
    ) +
    `<div class="settings-grid"><section class="panel"><div class="eyebrow">YOUR WORKSPACE</div><h2>${esc(user.workspace)}</h2><p>${esc(user.name)} · ${esc(user.email)}</p><span class="pill">${esc(user.role)}</span><p class="muted">${esc(user.retrieval)} retrieval · ${esc(user.mode)}</p><h3>Change password</h3><form id="password-form"><label>Current password<input name="current_password" type="password" autocomplete="current-password" required maxlength="128"></label><label>New password<input name="new_password" type="password" autocomplete="new-password" required minlength="10" maxlength="128"></label><button class="primary">Update password</button><div id="password-error" class="error"></div></form></section><section class="panel"><h3>Active sessions</h3><p class="muted">Updating your password revokes your other sessions.</p><div id="sessions"></div></section>${isAdmin ? `<section class="panel"><h3>Invite a team member</h3><p class="muted">They choose their own password using an invitation valid for 24 hours.</p><form id="invite-form"><label>Email<input name="email" type="email" required maxlength="254"></label><label>Role<select name="role"><option value="member">Member — upload and ask</option><option value="viewer">Viewer — read and ask</option><option value="admin">Administrator — manage workspace</option></select></label><button class="primary">Send invitation</button><div class="error" id="invite-error"></div></form></section><section class="panel"><h3>Workspace members</h3><div id="members"></div></section><section class="panel"><h3>Recent activity</h3><div id="activity"></div></section>` : ""}</div>`;
  $("#password-form").onsubmit = async (e) => {
    e.preventDefault();
    try {
      await post(
        "/auth/change-password",
        Object.fromEntries(new FormData(e.target)),
      );
      toast("Password updated. Other sessions were revoked.");
      await renderSettings();
    } catch (error) {
      $("#password-error").textContent = error.message;
    }
  };
  const sessions = await api("/auth/sessions");
  $("#sessions").innerHTML = sessions
    .map(
      (session) =>
        `<div class="activity-row"><strong>${session.current ? "This session" : "Another session"}</strong><small>${esc(session.agent)} · Expires ${date(session.expires * 1000)}</small><button class="text-button" data-revoke="${session.id}" data-current="${session.current}">Sign out ${session.current ? "here" : "this session"}</button></div>`,
    )
    .join("");
  document.querySelectorAll("[data-revoke]").forEach(
    (button) =>
      (button.onclick = async () => {
        try {
          await api("/auth/sessions/" + button.dataset.revoke, {
            method: "DELETE",
          });
          if (button.dataset.current === "true") {
            user = null;
            showAuth();
          } else {
            toast("Session revoked");
            await renderSettings();
          }
        } catch (error) {
          toast(error.message);
        }
      }),
  );
  if (isAdmin) {
    const [members, activity] = await Promise.all([
      api("/members"),
      api("/audit"),
    ]);
    $("#members").innerHTML = members
      .map(
        (m) =>
          `<div class="document-row"><span class="user-avatar">${esc(m.name[0])}</span><div><strong>${esc(m.name)}</strong><small>${esc(m.email)}</small></div><span class="pill">${esc(m.role)}</span></div>`,
      )
      .join("");
    $("#activity").innerHTML =
      activity
        .slice(0, 12)
        .map(
          (a) =>
            `<div class="activity-row">${esc(a.action.replaceAll(".", " "))}<small>${esc(a.name)} · ${date(a.created)}</small></div>`,
        )
        .join("") || '<p class="muted">No activity yet.</p>';
    $("#invite-form").onsubmit = async (e) => {
      e.preventDefault();
      try {
        const result = await post(
          "/invitations",
          Object.fromEntries(new FormData(e.target)),
        );
        toast(result.message);
        e.target.reset();
      } catch (error) {
        $("#invite-error").textContent = error.message;
      }
    };
  }
}
function recoveryForm() {
  modal(
    `<h2>Recover your account</h2><p class="muted">We'll send a one-use link to your account email.</p><form id="recovery-form"><label>Email<input name="email" type="email" autocomplete="email" required maxlength="254"></label><button class="primary">Send reset link</button><div id="recovery-message" role="status"></div></form>`,
  );
  $("#recovery-form").onsubmit = async (e) => {
    e.preventDefault();
    try {
      const result = await post(
        "/auth/forgot-password",
        Object.fromEntries(new FormData(e.target)),
      );
      $("#recovery-message").textContent = result.message;
    } catch (error) {
      $("#recovery-message").textContent = error.message;
    }
  };
}
$("#forgot-password").onclick = recoveryForm;
async function handleAccountLink() {
  const fragment = new URLSearchParams(location.hash.slice(1));
  const kind = fragment.has("reset")
    ? "reset"
    : fragment.has("invite")
      ? "invite"
      : null;
  if (!kind) return false;
  const token = fragment.get(kind);
  history.replaceState(null, "", location.pathname);
  showAuth();
  modal(
    `<h2>${kind === "reset" ? "Set a new password" : "Join your workspace"}</h2><form id="account-link-form">${kind === "invite" ? '<label>Your name<input name="name" autocomplete="name" required maxlength="100"></label>' : ""}<label>${kind === "reset" ? "New password" : "Choose your password"}<input name="password" type="password" autocomplete="new-password" required minlength="10" maxlength="128"></label><button class="primary">${kind === "reset" ? "Reset password" : "Accept invitation"}</button><div id="account-link-error" class="error"></div></form>`,
  );
  $("#account-link-form").onsubmit = async (e) => {
    e.preventDefault();
    try {
      await post(
        kind === "reset" ? "/auth/reset-password" : "/invitations/accept",
        { ...Object.fromEntries(new FormData(e.target)), token },
      );
      $("#modal").close();
      if (kind === "invite") await start();
      else {
        user = null;
        showAuth();
        if (registering) $("#auth-toggle").click();
        toast("Password reset. Sign in with your new password.");
      }
    } catch (error) {
      $("#account-link-error").textContent = error.message;
    }
  };
  return true;
}
async function initializeApp() {
  try {
    const config = await api("/app-config");
    if (config.auth_provider === "neon") {
      neonAuthClient = window.createKnowraNeonAuth(config.auth_url);
      $("#forgot-password").classList.add("hidden");
      const existing = await neonAuthClient.token();
      if (existing.data?.token) await post("/auth/neon", { token: existing.data.token });
    }
    if (config.demo) {
      $("#demo-notice").textContent = config.notice;
      $("#demo-notice").classList.remove("hidden");
      if (registering) $("#auth-toggle").click();
      $("#auth-title").textContent = "Explore the Knowra demo";
      $("#auth-subtitle").textContent = "Use the reviewer password supplied by the demo owner.";
      $("#auth-form [name=email]").value = config.login_email;
      document.querySelectorAll(".auth-switch").forEach(el => el.classList.add("hidden"));
      $(".privacy-note").textContent = "Shared fictional workspace. Do not enter private information.";
    }
  } catch {}
  if (!(await handleAccountLink())) start().catch(() => showAuth());
}
initializeApp();
