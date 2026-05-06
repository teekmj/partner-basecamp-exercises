// =============================================================
// Helios RFP Agent Platform — frontend
// Modes: run | scenarios | search | evals | arch | dev
// =============================================================

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));
const sleep = (ms) => new Promise(r => setTimeout(r, ms));

const STAGE_ORDER = ["parse", "retrieve_draft", "review", "export"];

const state = {
  mode: "run",
  answers: [],
  questions: [],
  review: null,
  final: null,
  currentScenarioId: null,
};

// ----- Top-nav (mode switching) -----
$$(".navtab").forEach(btn => {
  btn.addEventListener("click", () => switchMode(btn.dataset.mode));
});

function switchMode(mode) {
  state.mode = mode;
  $$(".navtab").forEach(b => b.classList.toggle("active", b.dataset.mode === mode));
  $$("main.mode").forEach(m => m.classList.toggle("hidden", m.dataset.mode !== mode));
  // Lazy-load tab content
  if (mode === "scenarios") loadScenarios();
  if (mode === "evals") { loadEvalSuites(); loadEvalHistory(); }
  if (mode === "present") loadPresentation();
  if (mode === "dev") { loadDevPrompts(); loadDevSpecialists(); loadDevKb(); loadDevLog(); }
}

async function loadDevSpecialists() {
  const r = await fetch("/api/specialists"); const d = await r.json();
  $("#dev-specialists-list").innerHTML = (d.specialists || []).map(s => `
    <div class="dev-kb-entry">
      <div class="dev-kb-source">🎓 ${esc(s.label)} <span class="cat-badge" style="margin-left:6px;">${esc(s.key)}</span></div>
      <div class="scenario-meta" style="margin-bottom:6px;">model=${esc(s.model)} · max_turns=${esc(s.max_turns)} · tools=[${(s.tools||[]).map(esc).join(", ")}]</div>
      <div class="dev-kb-content">${esc(s.description)}</div>
    </div>`).join("");
}

// ----- Inner-tab switching (works for any panel with .tabs/.tab-content) -----
$$(".tabs").forEach(tabsEl => {
  tabsEl.addEventListener("click", e => {
    const tab = e.target.closest(".tab");
    if (!tab) return;
    const target = tab.dataset.tab;
    const parent = tabsEl.parentElement;
    $$(".tab", tabsEl).forEach(t => t.classList.toggle("active", t === tab));
    $$(".tab-content", parent).forEach(c => c.classList.toggle("hidden", c.dataset.content !== target));
  });
});

// ===========================================================
// RUN MODE
// ===========================================================

const runEls = {
  rfp: $("#rfp-input"),
  apiKey: $("#api-key"),
  err: $("#error"),
  btnSample: $("#btn-sample"),
  btnParse: $("#btn-parse"),
  btnRun: $("#btn-run"),
  btnDemo: $("#btn-demo"),
  btnSaveScenario: $("#btn-save-scenario"),
  saveName: $("#save-name"),
  saveClient: $("#save-client"),
  optParallel: $("#opt-parallel"),
  activity: $("#activity"),
  answers: $("#answers"),
  answersEmpty: $("#answers-empty"),
  review: $("#review"),
  reviewEmpty: $("#review-empty"),
  qaScorecard: $("#qa-scorecard"),
  qaEmpty: $("#qa-empty"),
  demoNotes: $("#demo-notes"),
  demoEmpty: $("#demo-empty"),
  json: $("#json-output"),
  exportRow: $("#export-row"),
  btnExportHtml: $("#btn-export-html"),
};

// boot health
fetch("/api/health").then(r => r.json()).then(d => {
  $("#kb-count").textContent = `KB: ${d.kb_entries} · Scenarios: ${d.scenarios}`;
}).catch(() => { $("#kb-count").textContent = "KB: ?"; });

runEls.btnSample.addEventListener("click", async () => {
  const r = await fetch("/api/sample"); const d = await r.json();
  runEls.rfp.value = d.raw_text; showRunError(null);
});

runEls.btnParse.addEventListener("click", async () => {
  showRunError(null);
  const r = await fetch("/api/parse", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text: runEls.rfp.value }),
  });
  const d = await r.json();
  setStageStatus("parse", "done", `${d.count} questions`);
  ["retrieve_draft", "review", "export"].forEach(s => setStageStatus(s, null, "—"));
  renderQuestionPlaceholders(d.questions);
  log("info", `Parsed ${d.count} questions (no LLM call yet).`);
});

runEls.btnRun.addEventListener("click", () => runPipelineFromText(runEls.rfp.value, runEls.apiKey.value || null));

runEls.btnDemo.addEventListener("click", runDemo);

runEls.btnSaveScenario.addEventListener("click", async () => {
  const name = runEls.saveName.value.trim();
  const client = runEls.saveClient.value.trim();
  const text = runEls.rfp.value.trim();
  if (!name || !text) {
    showRunError("Need both a scenario name and questionnaire text to save.");
    return;
  }
  const r = await fetch("/api/scenarios", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name, client, text }),
  });
  if (!r.ok) { showRunError("Save failed."); return; }
  const d = await r.json();
  state.currentScenarioId = d.scenario.id;
  showRunError(null);
  showToast("✓", `Saved scenario: ${d.scenario.name}`, { success: true, duration: 3000 });
});

runEls.btnExportHtml.addEventListener("click", async () => {
  if (!state.final) return;
  const r = await fetch("/api/export/html", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ final: state.final }),
  });
  const blob = await r.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url; a.download = "rfp-response.html";
  document.body.appendChild(a); a.click(); a.remove();
  URL.revokeObjectURL(url);
  showToast("⬇", "HTML downloaded — open it and click Print to save as PDF.", { success: true, duration: 4500 });
});

async function runPipelineFromText(text, apiKey, options = {}) {
  showRunError(null);
  resetRunUI();
  setRunButtonsDisabled(true);

  const parallel = (runEls.optParallel ? runEls.optParallel.checked : true);

  try {
    const url = options.scenarioId ? `/api/scenarios/${options.scenarioId}/run` : "/api/run";
    const body = options.scenarioId
      ? { api_key: apiKey, parallel }
      : { text, api_key: apiKey, parallel };

    const resp = await fetch(url, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!resp.ok) {
      const d = await resp.json().catch(() => ({ error: "request failed" }));
      showRunError(d.error || "Pipeline failed."); return;
    }
    await readSse(resp, handleRunEvent);
  } finally {
    setRunButtonsDisabled(false);
  }
}

async function readSse(resp, handler) {
  const reader = resp.body.getReader();
  const decoder = new TextDecoder();
  let buf = "";
  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true });
    const events = buf.split("\n\n"); buf = events.pop();
    for (const e of events) {
      if (!e.startsWith("data: ")) continue;
      try { handler(JSON.parse(e.slice(6))); } catch {}
    }
  }
}

function setRunButtonsDisabled(b) {
  runEls.btnRun.disabled = b;
  runEls.btnDemo.disabled = b;
  runEls.btnSample.disabled = b;
  runEls.btnParse.disabled = b;
}

function handleRunEvent(evt) {
  switch (evt.type) {
    case "pipeline_start":
      log("stage_start", `Pipeline started: ${evt.rfp_name}`);
      if (evt.scenario_id) state.currentScenarioId = evt.scenario_id;
      break;
    case "stage_start":
      setStageStatus(evt.stage, "active", "running…");
      log("stage_start", `▶ ${evt.stage}`);
      break;
    case "stage_done":
      handleStageDone(evt); break;
    case "question_start":
      log("question_start", `▶ ${evt.qid} [${evt.category}]`);
      markQuestionPending(evt.qid);
      break;
    case "specialist_assigned":
      log("question_start", `   ${evt.qid} → routed to ${evt.specialist_label}`);
      markQuestionSpecialist(evt.qid, evt.specialist_label);
      break;
    case "tool_call":
      log("tool_call", `🔍 ${evt.qid} → search_kb("${evt.input.query || ""}", ${evt.input.category || "any"})`);
      break;
    case "tool_result":
      log("tool_result", `   ${evt.qid} ← ${evt.n_results} results: ${(evt.sources || []).join(", ")}`);
      break;
    case "answer_complete":
    case "question_done":
      handleAnswerEvent(evt.answer);
      break;
    case "pipeline_complete":
      log("stage_done", "🎉 Pipeline complete.");
      runEls.exportRow.classList.remove("hidden");
      break;
    case "scenario_updated":
      log("info", `Scenario ${evt.scenario_id} updated with this run.`);
      break;
    case "error":
      log("error", `ERROR: ${evt.error}`); showRunError(evt.error);
      break;
  }
}

function handleStageDone(evt) {
  if (evt.stage === "parse") {
    state.questions = evt.questions || [];
    setStageStatus("parse", "done", `${state.questions.length} questions`);
    renderQuestionPlaceholders(state.questions);
  } else if (evt.stage === "retrieve_draft") {
    setStageStatus("retrieve_draft", "done", `${state.answers.length} drafted`);
  } else if (evt.stage === "review") {
    state.review = evt.review;
    renderReview(evt.review);
    setStageStatus("review", "done", `score: ${(evt.review || {}).consistency_score || "?"}`);
  } else if (evt.stage === "qa_review") {
    state.qa = evt.qa_review;
    renderQAScorecard(evt.qa_review);
    const v = (evt.qa_review || {}).verdict || "?";
    const ov = (evt.qa_review || {}).overall || "?";
    setStageStatus("qa_review", "done", `${v} · ${ov}/10`);
  } else if (evt.stage === "demo") {
    state.demo = evt.demo_script;
    renderDemoNotes(evt.demo_script);
    setStageStatus("demo", "done", `${(evt.demo_script.top_talking_points || []).length} talking points`);
  } else if (evt.stage === "export") {
    state.final = evt.final;
    runEls.json.textContent = JSON.stringify(evt.final, null, 2);
    setStageStatus("export", "done", "ready");
  }
  log("stage_done", `✓ ${evt.stage}`);
}

function renderQAScorecard(qa) {
  if (!qa || qa.parse_error) {
    runEls.qaEmpty.classList.remove("hidden");
    runEls.qaScorecard.innerHTML = "";
    return;
  }
  runEls.qaEmpty.classList.add("hidden");
  const verdict = (qa.verdict || "ship").toLowerCase();
  const scores = qa.scores || {};
  const cells = ["accuracy", "completeness", "cite_quality", "tone_consistency"].map(k => {
    const v = scores[k] ?? "?";
    let kls = "";
    const iv = parseInt(v, 10);
    if (!isNaN(iv)) {
      if (iv < 5) kls = "bad";
      else if (iv < 8) kls = "med";
    }
    return `<div class="qa-score-cell"><div class="lbl">${esc(k.replace(/_/g, " "))}</div><div class="val ${kls}">${esc(v)}</div></div>`;
  }).join("");

  const issues = (qa.top_issues || []).map(i => `<li>${esc(i)}</li>`).join("");
  const strengths = (qa.strengths || []).map(s => `<li>${esc(s)}</li>`).join("");

  runEls.qaScorecard.innerHTML = `
    <div class="qa-card ${esc(verdict)}">
      <div>
        <span class="verdict ${esc(verdict)}">${esc(verdict.replace(/_/g, " "))}</span>
        <strong>Overall: ${esc(qa.overall ?? "?")}/10</strong>
      </div>
      <p style="margin: 10px 0; color: var(--muted); font-size: 13px;">${esc(qa.summary || "")}</p>
      <div class="qa-scores">${cells}</div>
      ${issues ? `<h4>Top issues</h4><ul>${issues}</ul>` : ""}
      ${strengths ? `<h4>Strengths</h4><ul>${strengths}</ul>` : ""}
    </div>`;
}

function renderDemoNotes(demo) {
  if (!demo || demo.parse_error) {
    runEls.demoEmpty.classList.remove("hidden");
    runEls.demoNotes.innerHTML = "";
    return;
  }
  runEls.demoEmpty.classList.add("hidden");

  const cp = demo.client_pitch || {};
  const pillars = (cp.value_pillars || []).map(p => `
    <div class="pillar-card">
      <div class="pillar-title">${esc(p.title || "")}</div>
      <div class="pillar-body">${esc(p.body || "")}</div>
    </div>`).join("");
  const whyParas = (cp.why_helios || "")
    .split(/\n\n+/)
    .filter(s => s.trim())
    .map(p => `<p>${esc(p)}</p>`)
    .join("");

  const clientPitchSection = (cp.headline || cp.why_helios || (cp.value_pillars || []).length) ? `
    <div class="client-pitch-card">
      <div class="cp-label">Client-facing pitch (goes into the PDF)</div>
      ${cp.headline ? `<div class="cp-headline">${esc(cp.headline)}</div>` : ""}
      ${cp.tailored_to ? `<div class="cp-tailored">Tailored to: ${esc(cp.tailored_to)}</div>` : ""}
      ${whyParas ? `<div class="cp-narrative">${whyParas}</div>` : ""}
      ${pillars ? `<div class="cp-pillars">${pillars}</div>` : ""}
    </div>` : "";

  const points = (demo.top_talking_points || []).map(p => `<li>${esc(p)}</li>`).join("");
  const diffs = (demo.key_differentiators || []).map(d => `<li>${esc(d)}</li>`).join("");
  const followups = (demo.likely_followups || []).map(f => `
    <div class="demo-followup">
      <div class="q">Q: ${esc(f.question || "")}</div>
      <div class="a">${esc(f.answer_hint || "")}</div>
    </div>`).join("");

  runEls.demoNotes.innerHTML = `
    ${clientPitchSection}
    <div class="demo-notes-card">
      <h4 style="margin-top:0;">AE speaker notes (internal)</h4>
      <h4>Elevator pitch</h4>
      <div class="demo-pitch">${esc(demo.elevator_pitch || "")}</div>
      <h4>Lead with these talking points</h4>
      <ol>${points}</ol>
      <h4>Key differentiators</h4>
      <ul>${diffs}</ul>
      <h4>Likely follow-up questions</h4>
      ${followups}
      <h4>Recommended next step</h4>
      <div class="demo-cta">${esc(demo.call_to_action || "")}</div>
    </div>`;
}

function handleAnswerEvent(ans) {
  if (!state.answers.find(a => a.question_id === ans.question_id)) {
    state.answers.push(ans);
  }
  renderAnswer(ans);
  log("question_done", `✓ ${ans.question_id} confidence=${ans.confidence} sources=${(ans.sources || []).length}`);
}

function setStageStatus(stage, status, detail) {
  const el = $(`.stage[data-stage="${stage}"]`);
  if (!el) return;
  if (status) el.dataset.status = status; else delete el.dataset.status;
  const d = $(`[data-detail-for="${stage}"]`);
  if (d) d.textContent = detail || "—";
}

function resetRunUI() {
  ["parse", "retrieve_draft", "review", "qa_review", "demo", "export"].forEach(s => setStageStatus(s, null, "—"));
  state.answers = []; state.questions = [];
  state.review = null; state.qa = null; state.demo = null; state.final = null;
  runEls.activity.innerHTML = "";
  runEls.answers.innerHTML = "";
  runEls.review.innerHTML = "";
  if (runEls.qaScorecard) runEls.qaScorecard.innerHTML = "";
  if (runEls.demoNotes) runEls.demoNotes.innerHTML = "";
  runEls.json.textContent = "";
  runEls.answersEmpty.classList.add("hidden");
  runEls.reviewEmpty.classList.add("hidden");
  if (runEls.qaEmpty) runEls.qaEmpty.classList.remove("hidden");
  if (runEls.demoEmpty) runEls.demoEmpty.classList.remove("hidden");
  runEls.exportRow.classList.add("hidden");
}

function renderQuestionPlaceholders(qs) {
  runEls.answers.innerHTML = "";
  runEls.answersEmpty.classList.add("hidden");
  qs.forEach(q => {
    const div = document.createElement("div");
    div.className = "answer-card pending";
    div.id = `card-${q.id}`;
    div.dataset.confidence = "medium";
    div.innerHTML = `
      <div class="answer-head">
        <div class="answer-title">
          <span class="answer-id">${esc(q.id)}</span>
          <span class="cat-badge">${esc(q.category)}</span>
        </div>
        <span class="confidence-badge medium">drafting…</span>
      </div>
      <div class="answer-question">${esc(q.text)}</div>
      <div class="answer-body hint">⏳ Waiting for agent…</div>`;
    runEls.answers.appendChild(div);
  });
}

function markQuestionPending(qid) {
  const card = $(`#card-${qid}`); if (!card) return;
  const body = card.querySelector(".answer-body");
  if (body) body.textContent = "🔍 Searching knowledge base…";
}

function markQuestionSpecialist(qid, label) {
  const card = $(`#card-${qid}`); if (!card) return;
  // Insert/update a specialist chip in the head
  let chip = card.querySelector(".specialist-chip");
  if (!chip) {
    chip = document.createElement("span");
    chip.className = "specialist-chip";
    const head = card.querySelector(".answer-title");
    if (head) head.appendChild(chip);
  }
  chip.textContent = `🎓 ${label}`;
}

function renderAnswer(ans) {
  let card = $(`#card-${ans.question_id}`);
  if (!card) {
    card = document.createElement("div");
    card.id = `card-${ans.question_id}`;
    card.className = "answer-card";
    runEls.answers.appendChild(card);
  }
  card.dataset.confidence = ans.confidence || "medium";
  card.classList.remove("pending");
  const sources = (ans.sources || []).map(s => `<span class="source-chip">${esc(s)}</span>`).join("");
  const flags = (ans.flags || []).map(f => `<span class="flag">⚠ ${esc(f)}</span>`).join("");
  const specialist = ans.specialist_label
    ? `<span class="specialist-chip">🎓 ${esc(ans.specialist_label)}</span>`
    : "";
  card.innerHTML = `
    <div class="answer-head">
      <div class="answer-title">
        <span class="answer-id">${esc(ans.question_id)}</span>
        <span class="cat-badge">${esc(ans.category || "")}</span>
        ${specialist}
      </div>
      <span class="confidence-badge ${ans.confidence || 'medium'}">${esc(ans.confidence || '?')}</span>
    </div>
    <div class="answer-body">${esc(ans.answer || "")}</div>
    <div class="answer-sources">
      <strong>Sources:</strong> ${sources || '<em>none</em>'}
      ${flags ? `<div style="margin-top:6px;"><strong>Flags:</strong> ${flags}</div>` : ''}
    </div>`;
}

function renderReview(review) {
  runEls.reviewEmpty.classList.add("hidden");
  const score = (review.consistency_score || "unknown").toLowerCase();
  const issues = review.issues || [];
  const recs = review.recommendations || [];
  runEls.review.innerHTML = `
    <div class="review-summary">
      <div class="consistency-ring ${score}">${score}</div>
      <div>
        <div style="font-weight:600;font-size:14px;">Consistency: ${score}</div>
        <div class="hint">${issues.length} issue${issues.length === 1 ? '' : 's'} flagged · ${recs.length} recommendation${recs.length === 1 ? '' : 's'}</div>
      </div>
    </div>
    <div class="review-issues">
      <h4>Issues (${issues.length})</h4>
      ${issues.length === 0 ? '<p class="hint">No issues found ✓</p>' : `<ul>${issues.map(i => `<li>${formatIssue(i)}</li>`).join("")}</ul>`}
    </div>
    <div class="review-recommendations">
      <h4>Recommendations (${recs.length})</h4>
      ${recs.length === 0 ? '<p class="hint">None.</p>' : `<ul>${recs.map(r => `<li>${esc(typeof r === 'string' ? r : JSON.stringify(r))}</li>`).join("")}</ul>`}
    </div>`;
}

function formatIssue(i) {
  if (typeof i === "string") return esc(i);
  if (typeof i === "object" && i !== null) {
    const type = i.type ? `<strong>[${esc(i.type)}]</strong> ` : "";
    return type + esc(i.description || i.issue || JSON.stringify(i));
  }
  return esc(String(i));
}

function log(tag, msg) {
  const line = document.createElement("div");
  line.className = `line tag-${tag}`;
  line.innerHTML = `<span class="ts">${new Date().toLocaleTimeString()}</span>${esc(msg)}`;
  runEls.activity.appendChild(line);
  runEls.activity.scrollTop = runEls.activity.scrollHeight;
}

function showRunError(msg) {
  if (!msg) { runEls.err.textContent = ""; runEls.err.classList.add("hidden"); return; }
  runEls.err.textContent = msg; runEls.err.classList.remove("hidden");
}

// ===========================================================
// SCENARIOS MODE
// ===========================================================

$("#btn-refresh-scenarios").addEventListener("click", loadScenarios);
$("#btn-new-scenario").addEventListener("click", () => switchMode("run"));
$("#btn-seed-scenarios").addEventListener("click", async () => {
  const r = await fetch("/api/scenarios/seed", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: "{}",
  });
  const d = await r.json();
  showToast("🌱", `Seeded: +${d.saved} new · ${d.skipped} already present (${d.total} total)`, { success: true, duration: 4000 });
  loadScenarios();
});
$("#scenarios-filter").addEventListener("input", (e) => filterScenarios(e.target.value));

let _scenariosCache = [];

async function loadScenarios() {
  const r = await fetch("/api/scenarios"); const d = await r.json();
  _scenariosCache = d.scenarios || [];
  renderScenarios(_scenariosCache);
}

function filterScenarios(query) {
  const q = (query || "").toLowerCase().trim();
  if (!q) { renderScenarios(_scenariosCache); return; }
  const filtered = _scenariosCache.filter(s => {
    return (s.name || "").toLowerCase().includes(q)
      || (s.client || "").toLowerCase().includes(q)
      || (s.description || "").toLowerCase().includes(q);
  });
  renderScenarios(filtered);
}

function renderScenarios(list) {
  const container = $("#scenarios-list");
  if (!list.length) {
    container.innerHTML = '<p class="hint">No scenarios match. Try the <strong>🌱 Seed 50 samples</strong> button to populate the corpus.</p>';
    return;
  }
  container.innerHTML = list.map(s => `
    <div class="scenario-card ${s.has_result ? 'has-result' : ''}" data-id="${esc(s.id)}">
      <div class="scenario-card-head">
        <div>
          <div class="scenario-name">${esc(s.name)}</div>
          <div class="scenario-client">${esc(s.client || 'no client')}</div>
        </div>
        <div class="scenario-meta" style="text-align:right;">
          ${s.question_count} q
          ${s.has_result ? '· ✓ run' : '· not run'}
        </div>
      </div>
      ${s.description ? `<div class="scenario-desc">${esc(s.description)}</div>` : ''}
      <div class="scenario-actions">
        <button data-action="run" data-id="${esc(s.id)}" class="primary">▶ Run</button>
        <button data-action="load" data-id="${esc(s.id)}" class="ghost">📝 Edit</button>
        <button data-action="clone" data-id="${esc(s.id)}" class="ghost">📋 Clone</button>
        <button data-action="export" data-id="${esc(s.id)}" class="ghost" ${s.has_result ? '' : 'disabled'}>⬇ HTML</button>
        <button data-action="delete" data-id="${esc(s.id)}" class="ghost">🗑</button>
      </div>
    </div>
  `).join("");
  // Wire actions
  $$("[data-action]", container).forEach(btn => btn.addEventListener("click", () => scenarioAction(btn.dataset.action, btn.dataset.id)));
}

async function scenarioAction(action, sid) {
  if (action === "delete") {
    if (!confirm("Delete this scenario permanently?")) return;
    await fetch(`/api/scenarios/${sid}`, { method: "DELETE" });
    loadScenarios();
  } else if (action === "clone") {
    await fetch(`/api/scenarios/${sid}/clone`, { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" });
    loadScenarios();
  } else if (action === "load") {
    const r = await fetch(`/api/scenarios/${sid}`); const d = await r.json();
    const s = d.scenario;
    const text = (s.questions || []).map(q => `${q.id || ''}. ${q.text || ''}`).join("\n\n");
    runEls.rfp.value = text;
    runEls.saveName.value = s.name || "";
    runEls.saveClient.value = s.client || "";
    state.currentScenarioId = sid;
    switchMode("run");
  } else if (action === "run") {
    switchMode("run");
    await runPipelineFromText(null, runEls.apiKey.value || null, { scenarioId: sid });
  } else if (action === "export") {
    const r = await fetch("/api/export/html", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ scenario_id: sid }),
    });
    if (!r.ok) { alert("No result attached to this scenario yet."); return; }
    const blob = await r.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url; a.download = `rfp-${sid}.html`;
    document.body.appendChild(a); a.click(); a.remove();
    URL.revokeObjectURL(url);
  }
}

// ===========================================================
// SEARCH MODE
// ===========================================================

$("#btn-search").addEventListener("click", runSearch);
$("#search-input").addEventListener("keydown", e => { if (e.key === "Enter") runSearch(); });

async function runSearch() {
  const query = $("#search-input").value.trim();
  if (!query) return;
  const types = $$(".search-type:checked").map(c => c.value);
  const r = await fetch("/api/search", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ query, types }),
  });
  const d = await r.json();
  const container = $("#search-results");
  if (!d.results || !d.results.length) {
    container.innerHTML = `<p class="hint">No results for <strong>${esc(query)}</strong>.</p>`;
    return;
  }
  container.innerHTML = d.results.map(r => {
    const snippet = highlightSnippet(r.snippet, query);
    return `
      <div class="search-result ${esc(r.type)}">
        <div class="search-result-head">
          <div class="search-result-title">${esc(r.title)}</div>
          <div class="search-result-type">${esc(r.type)} · ${r.score}</div>
        </div>
        <div class="search-result-snippet">${snippet}</div>
        <div class="search-result-meta">${esc(r.location)}${r.tags && r.tags.length ? ' · ' + r.tags.map(t => esc(t)).join(' · ') : ''}</div>
      </div>`;
  }).join("");
}

function highlightSnippet(text, query) {
  const escaped = esc(text || "");
  const terms = (query || "").toLowerCase().split(/\s+/).filter(t => t.length > 1);
  let out = escaped;
  terms.forEach(t => {
    // case-insensitive replace, escape regex metachars
    const re = new RegExp(`(${t.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")})`, "gi");
    out = out.replace(re, "<mark>$1</mark>");
  });
  return out;
}

// ===========================================================
// EVALS MODE
// ===========================================================

async function loadEvalSuites() {
  const r = await fetch("/api/evals/suites"); const d = await r.json();
  $("#eval-suites").innerHTML = d.suites.map(s => `
    <div class="suite-card">
      <div class="suite-name">${esc(s.name)}</div>
      <div class="suite-desc">${esc(s.description)}</div>
      <button class="primary" data-suite="${esc(s.id)}">▶ Run suite</button>
    </div>`).join("");
  $$("#eval-suites button[data-suite]").forEach(b => b.addEventListener("click", () => runEvalSuite(b.dataset.suite)));
}

async function loadEvalHistory() {
  const r = await fetch("/api/evals/runs"); const d = await r.json();
  $("#eval-history").innerHTML = renderEvalHistoryRows(d.runs, "No past eval runs.");
  // Also load archive
  const ra = await fetch("/api/evals/archive"); const da = await ra.json();
  $("#eval-archive-list").innerHTML = renderEvalHistoryRows(da.runs, "Archive empty.");
}

function renderEvalHistoryRows(runs, emptyMsg) {
  if (!runs || !runs.length) return `<p class="hint">${emptyMsg}</p>`;
  return runs.slice().reverse().map(r => {
    const klass = r.pass_rate >= 95 ? "high" : r.pass_rate >= 70 ? "medium" : "low";
    const ts = new Date((r.timestamp || 0) * 1000).toLocaleString();
    return `<div class="eval-history-row">
      <span class="left">${ts} · ${esc(r.suite)}</span>
      <span class="right ${klass}">${r.passed}/${r.total} (${r.pass_rate}%) · ${r.elapsed_s}s</span>
    </div>`;
  }).join("");
}

async function runEvalSuite(suite) {
  $("#eval-active").classList.remove("hidden");
  $("#eval-progress").innerHTML = "";
  $("#eval-result").classList.add("hidden");
  $("#eval-result").innerHTML = "";

  const apiKey = runEls.apiKey.value || null;
  const resp = await fetch("/api/evals/run", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ suite, api_key: apiKey }),
  });
  if (!resp.ok) { alert("Eval start failed"); return; }

  await readSse(resp, evt => {
    if (evt.type === "step") {
      const line = document.createElement("div");
      line.className = "line tag-stage_start";
      line.textContent = evt.message;
      $("#eval-progress").appendChild(line);
      $("#eval-progress").scrollTop = $("#eval-progress").scrollHeight;
    } else if (evt.type === "eval_complete") {
      renderEvalResult(evt.result);
    } else if (evt.type === "error") {
      alert("Eval error: " + evt.error);
    }
  });
  loadEvalHistory();
}

function renderEvalResult(r) {
  const klass = r.pass_rate >= 95 ? "" : r.pass_rate >= 70 ? "medium" : "bad";
  const byQ = {};
  r.assertions.forEach(a => {
    const k = a.qid || "global";
    if (!byQ[k]) byQ[k] = [];
    byQ[k].push(a);
  });

  const html = `
    <div class="eval-summary">
      <div class="eval-summary-head">
        <div style="font-weight:600;font-size:14px;">${esc(r.suite)}</div>
        <div class="eval-progress-bar"><div class="eval-progress-fill ${klass}" style="width:${r.pass_rate}%"></div></div>
        <div style="font-weight:600;font-family:monospace;">${r.passed}/${r.total} (${r.pass_rate}%)</div>
      </div>
      <div class="eval-summary-stats">
        <span>Passed: <strong>${r.passed}</strong></span>
        <span>Failed: <strong>${r.failed}</strong></span>
        <span>Time: <strong>${r.elapsed_s}s</strong></span>
      </div>
      <div class="eval-asserts">
        ${r.assertions.map(a => `
          <div class="eval-assert ${a.passed ? 'pass' : 'fail'}">
            <span class="ico">${a.passed ? '✓' : '✗'}</span>
            <span class="qid">${esc(a.qid || '—')}</span>
            <span class="name">${esc(a.test)}</span>
            <span class="detail">${esc(a.detail || '')}</span>
          </div>`).join("")}
      </div>
    </div>`;
  $("#eval-result").innerHTML = html;
  $("#eval-result").classList.remove("hidden");
}

// ===========================================================
// DEV MODE
// ===========================================================

async function loadDevPrompts() {
  const r = await fetch("/api/dev/prompts"); const d = await r.json();
  $("#dev-system-prompt").textContent = d.system_prompt || "(empty)";
  $("#dev-review-prompt").textContent = d.review_prompt_template || "(empty)";
}

async function loadDevKb() {
  const r = await fetch("/api/dev/prompts"); const d = await r.json();
  $("#dev-kb-list").innerHTML = (d.kb_full || []).map(e => `
    <div class="dev-kb-entry">
      <div class="dev-kb-source">${esc(e.source)}</div>
      <div class="dev-kb-tags">${(e.tags || []).map(t => `<span class="dev-kb-tag">${esc(t)}</span>`).join("")}</div>
      <div class="dev-kb-content">${esc(e.content)}</div>
    </div>`).join("");
}

$("#btn-refresh-log").addEventListener("click", loadDevLog);
$("#btn-clear-log").addEventListener("click", async () => {
  await fetch("/api/dev/log/clear", { method: "POST" });
  loadDevLog();
});

async function loadDevLog() {
  const r = await fetch("/api/dev/log?limit=200"); const d = await r.json();
  const rows = (d.entries || []).slice().reverse();
  const head = `<div class="log-row head">
    <span>Time</span><span>Method</span><span>Path</span><span>Status</span><span>ms</span>
  </div>`;
  const body = rows.map(e => {
    const t = new Date((e.timestamp || 0) * 1000).toLocaleTimeString();
    const sclass = `status-${String(e.status || 0).charAt(0)}`;
    return `<div class="log-row">
      <span>${esc(t)}</span>
      <span>${esc(e.method || '')}</span>
      <span>${esc(e.path || '')}</span>
      <span class="${sclass}">${esc(e.status || '')}</span>
      <span>${esc(e.elapsed_ms || '')}</span>
    </div>`;
  }).join("");
  $("#dev-log-table").innerHTML = head + (rows.length ? body : '<p class="hint" style="padding:14px;">No entries yet.</p>');
}

// ===========================================================
// PRESENTATION MODE — slide deck
// ===========================================================

const SLIDES = [
  {
    title: "Helios RFP Agent Platform",
    subtitle: "Multi-agent system for automated RFP response drafting",
    body: `
      <h3>The problem</h3>
      <p>Helios sales engineers spend <strong>6–8 hours per RFP</strong> hunting through Confluence, copy-pasting answers, and missing cross-question contradictions.</p>
      <h3>What we built</h3>
      <p>A 6-stage multi-agent platform that drafts a complete, reviewed, demo-ready RFP response in <strong>under 90 seconds</strong>.</p>
    `,
  },
  {
    title: "Six specialist agents",
    body: `
      <p>Each question is routed to a specialist with a tailored persona and tool access. After drafting, two more agents review quality and prepare presenter notes.</p>
      <div class="agent-grid">
        <div class="agent-card"><div class="role">🎓 Solutions Architect</div><div class="desc">Technical questions: detection, latency, encryption, throughput.</div></div>
        <div class="agent-card"><div class="role">🎓 Compliance Officer</div><div class="desc">SOC 2, ISO 27001, FedRAMP, GDPR — exact audit dates &amp; bodies.</div></div>
        <div class="agent-card"><div class="role">🎓 Pricing Lead</div><div class="desc">Per-tier pricing, mid-tier interpolation, multi-year discounts.</div></div>
        <div class="agent-card"><div class="role">🎓 Customer Success Lead</div><div class="desc">Customer counts, references, NPS, vertical breakdowns.</div></div>
        <div class="agent-card"><div class="role">📊 Senior Reviewer</div><div class="desc">Scores accuracy, completeness, citations, tone — 0–10 each. Returns ship / revise verdict.</div></div>
        <div class="agent-card"><div class="role">🎤 Sales Engineering Lead</div><div class="desc">Generates elevator pitch, talking points, follow-up Qs, call-to-action.</div></div>
      </div>
      <p style="font-size:13px;color:var(--muted);">All six are configured as <code>claude_agent_sdk.AgentDefinition</code> objects.</p>
    `,
  },
  {
    title: "The pipeline",
    body: `
      <pre style="background:var(--panel);padding:18px;border-radius:8px;font-size:13px;line-height:1.7;">
┌───────┐  ┌──────────────┐  ┌─────────────┐  ┌────────┐  ┌──────┐  ┌────────┐
│ PARSE │→ │ DRAFT (4×    │→ │ CONSISTENCY │→ │  QA    │→ │ DEMO │→ │ EXPORT │
│       │  │ specialists  │  │   REVIEW    │  │ SCORE  │  │      │  │  PDF/  │
│       │  │ in parallel) │  │             │  │        │  │      │  │  HTML  │
└───────┘  └──────────────┘  └─────────────┘  └────────┘  └──────┘  └────────┘
      </pre>
      <h3>Why parallel?</h3>
      <p>Sequential drafting = ~80s for 5 questions. Parallel drafting (4 workers) = ~25s. <strong>3× faster</strong> with no quality loss.</p>
    `,
  },
  {
    title: "Live measured performance",
    body: `
      <div class="stat-row">
        <div class="stat-card"><div class="num">66s</div><div class="lbl">Median latency / RFP (p50)</div></div>
        <div class="stat-card"><div class="num">100%</div><div class="lbl">Trials with consistency = high (n=100)</div></div>
        <div class="stat-card"><div class="num">100%</div><div class="lbl">Source-citation rate</div></div>
        <div class="stat-card"><div class="num">$0.50</div><div class="lbl">Cost per RFP (Opus 4.7)</div></div>
      </div>
      <p>Stability validated over <strong>100 independent trials</strong>: zero structural failures, zero invalid confidence values, all expected facts present every time.</p>
    `,
  },
  {
    title: "Quality assurance",
    body: `
      <h3>Two-layer review</h3>
      <ul>
        <li><strong>Consistency review</strong> — flags contradictions across answers (SOC 2 dates that disagree, SIEM positioning conflicts, etc.)</li>
        <li><strong>QA scorecard</strong> — Senior Reviewer grades 4 dimensions on a 0–10 scale: <em>accuracy · completeness · cite_quality · tone_consistency</em>, plus a ship/revise verdict.</li>
      </ul>
      <h3>Eval framework</h3>
      <ul>
        <li>4 suites: smoke · factual · edge · full</li>
        <li>Fuzzy assertion primitives tolerate LLM phrasing variations</li>
        <li>Every run dual-writes: live log (mutable) + durable archive (committed to repo)</li>
      </ul>
    `,
  },
  {
    title: "Outputs ready for the prospect",
    body: `
      <h3>Self-contained HTML</h3>
      <ul>
        <li><strong>Cover page</strong> with prospect name and "Prepared for" header</li>
        <li><strong>Executive summary</strong> with at-a-glance stats</li>
        <li><strong>QA scorecard</strong> with per-dimension scores</li>
        <li><strong>Drafted answers</strong> with category, confidence, sources, flags</li>
        <li><strong>Consistency review</strong> with score ring</li>
        <li><strong>Sales presenter notes</strong> from the Demoer</li>
      </ul>
      <p>Click the <strong>🖨️ Print / Save as PDF</strong> button in the exported HTML to produce a polished PDF — no extra dependencies needed.</p>
    `,
  },
  {
    title: "Try it now",
    body: `
      <h3>Quick path</h3>
      <ol>
        <li>Click <strong>📂 Scenarios</strong> in the top nav</li>
        <li>Pick any of the <strong>50 seeded RFPs</strong> across 12 fictional clients</li>
        <li>Click <strong>▶ Run</strong> on a card and watch the 6 stages light up</li>
        <li>Click <strong>⬇ HTML</strong> to download the prospect-ready document</li>
        <li>Open the HTML and click <strong>Print → Save as PDF</strong></li>
      </ol>
      <h3>Or run your own</h3>
      <p>Click <strong>▶ Run</strong> in the top nav, paste any RFP, and run the pipeline. Save it as a scenario for later.</p>
    `,
  },
];

let _slideIdx = 0;

function loadPresentation() {
  const stage = $("#slide-stage");
  stage.innerHTML = SLIDES.map((s, i) => `
    <div class="slide${i === 0 ? ' active' : ''}" data-slide-idx="${i}">
      <h1>${s.title}</h1>
      ${s.subtitle ? `<h2>${s.subtitle}</h2>` : ""}
      ${s.body}
      <div class="slide-num">${i + 1} / ${SLIDES.length}</div>
    </div>
  `).join("");
  _slideIdx = 0;
  updateSlideCounter();
}

function showSlide(idx) {
  if (idx < 0) idx = 0;
  if (idx > SLIDES.length - 1) idx = SLIDES.length - 1;
  _slideIdx = idx;
  $$(".slide").forEach((el, i) => el.classList.toggle("active", i === idx));
  updateSlideCounter();
}

function updateSlideCounter() {
  const c = $("#slide-counter");
  if (c) c.textContent = `${_slideIdx + 1} / ${SLIDES.length}`;
}

document.addEventListener("keydown", (e) => {
  if (state.mode !== "present") return;
  if (e.key === "ArrowRight") showSlide(_slideIdx + 1);
  if (e.key === "ArrowLeft") showSlide(_slideIdx - 1);
  if (e.key === "f" || e.key === "F") {
    const stage = $("#slide-stage");
    if (stage && stage.requestFullscreen) stage.requestFullscreen().catch(() => {});
  }
});

$("#btn-slide-prev").addEventListener("click", () => showSlide(_slideIdx - 1));
$("#btn-slide-next").addEventListener("click", () => showSlide(_slideIdx + 1));
$("#btn-slide-fullscreen").addEventListener("click", () => {
  const stage = $("#slide-stage");
  if (stage && stage.requestFullscreen) stage.requestFullscreen().catch(() => {});
});

// ===========================================================
// Demo + toast (kept from earlier)
// ===========================================================

function activateOutputTab(name) {
  const tabs = $(".output-panel .tabs"); if (!tabs) return;
  $$(".tab", tabs).forEach(t => t.classList.toggle("active", t.dataset.tab === name));
  $$(".tab-content", $(".output-panel")).forEach(c => c.classList.toggle("hidden", c.dataset.content !== name));
}

function showToast(step, message, options = {}) {
  const old = document.querySelector(".demo-toast");
  if (old) old.remove();
  const toast = document.createElement("div");
  toast.className = "demo-toast" + (options.success ? " success" : "");
  toast.innerHTML = `<div class="step">${esc(String(step))}</div><div>${esc(message)}</div>`;
  document.body.appendChild(toast);
  if (options.duration) setTimeout(() => toast.remove(), options.duration);
}

async function runDemo() {
  setRunButtonsDisabled(true);
  resetRunUI();
  try {
    showToast(1, "First, let me show the system architecture", { duration: 4000 });
    switchMode("arch");
    await sleep(4000);

    switchMode("run");
    showToast(2, "Loading a 5-question RFP from a cybersecurity vendor", { duration: 3000 });
    const sampleResp = await fetch("/api/sample"); const sample = await sampleResp.json();
    runEls.rfp.value = sample.raw_text;
    activateOutputTab("answers");
    await sleep(3000);

    showToast(3, "Now running the pipeline live — watch the stages light up");
    const runResp = await fetch("/api/run", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text: runEls.rfp.value, api_key: runEls.apiKey.value || null }),
    });
    if (!runResp.ok) { showRunError("Demo failed"); return; }
    let firstAns = false;
    await readSse(runResp, async (evt) => {
      handleRunEvent(evt);
      if (evt.type === "stage_done" && evt.stage === "parse") {
        showToast(4, `Parsed ${evt.questions.length} questions`);
      }
      if (evt.type === "question_done" && !firstAns) {
        firstAns = true;
        showToast(5, "Drafting answers — each searches the KB and cites sources");
      }
      if (evt.type === "stage_done" && evt.stage === "retrieve_draft") {
        showToast(6, "All drafted — running cross-question consistency review");
      }
      if (evt.type === "stage_done" && evt.stage === "review") {
        const score = evt.review.consistency_score;
        showToast(7, `Review: score ${score}, ${(evt.review.issues || []).length} issues`);
        await sleep(1500);
        activateOutputTab("review");
      }
      if (evt.type === "pipeline_complete") {
        await sleep(3000);
        activateOutputTab("json");
        showToast(8, "Final exported JSON deliverable", { duration: 4000 });
        await sleep(4500);
        activateOutputTab("answers");
        showToast("✓", "Demo complete. Try the Scenarios, Search, Evals, and Dev tabs.", { success: true, duration: 6000 });
      }
    });
  } catch (e) {
    showRunError("Demo error: " + e.message);
  } finally {
    setRunButtonsDisabled(false);
  }
}

// ===========================================================
// Utility
// ===========================================================
function esc(s) {
  return String(s == null ? "" : s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}
