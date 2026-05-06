# Helios RFP Agent — Architecture

## 1. System overview

The system has two layers wrapped around a five-stage agent pipeline.

```
┌────────────────────────────────────────────────────────────────────┐
│                           BROWSER (UI)                             │
│  static/index.html · static/app.js · static/styles.css             │
│  ┌───────────────┐  ┌────────────────────┐  ┌──────────────────┐   │
│  │ Input panel   │  │ Pipeline visualizer│  │ Output panel     │   │
│  │ (textarea +   │  │ (4 stages light up │  │ (Answers / Review│   │
│  │  controls)    │  │  + activity feed)  │  │  / JSON tabs)    │   │
│  └───────┬───────┘  └────────▲───────────┘  └──────────────────┘   │
│          │                   │                                     │
│  POST /api/run               │ SSE: data: {...} per event          │
└──────────┼───────────────────┼─────────────────────────────────────┘
           │                   │
┌──────────▼───────────────────┴─────────────────────────────────────┐
│                      FLASK BACKEND (app.py)                        │
│                                                                    │
│  /api/health    /api/sample    /api/kb                             │
│  /api/parse     /api/retrieve  (utility endpoints, no LLM)         │
│  /api/run       (SSE stream → run_pipeline + on_event callback)    │
└──────────────────────┬─────────────────────────────────────────────┘
                       │
┌──────────────────────▼─────────────────────────────────────────────┐
│                  AGENT PIPELINE (agent_core.py)                    │
│                                                                    │
│   ┌─────────┐   ┌──────────┐   ┌──────────┐   ┌──────────┐         │
│   │  PARSE  │──▶│ RETRIEVE │──▶│  DRAFT   │──▶│  REVIEW  │──▶ EXPORT
│   │         │   │          │   │ (LLM +   │   │  (LLM)   │         │
│   │  no LLM │   │ keyword  │   │  tool    │   │          │         │
│   │         │   │ scoring  │   │  loop)   │   │          │         │
│   └─────────┘   └──────────┘   └──────────┘   └──────────┘         │
│                                                                    │
│              ▲                                                     │
│              │                                                     │
│   ┌──────────┴───────────┐                                         │
│   │ KNOWLEDGE_BASE (in   │                                         │
│   │ memory · 5 entries)  │                                         │
│   └──────────────────────┘                                         │
└────────────────────────────────────────────────────────────────────┘
                       │
                       ▼
              Anthropic Messages API
              (claude-opus-4-7)
```

## 2. The five stages

### Stage 1 — Parse  (`parse_questionnaire`, no LLM)

**Input:** raw text
**Output:** `list[{id, category, text}]`

Accepts three formats:
- **JSON list** `[{"id": "Q1", ...}]` — used as-is
- **Blank-line-separated paragraphs** — each becomes one question
- **Numbered/bulleted list** — `1.`, `Q1.`, `-`, `*` markers stripped

Categories are inferred via keyword matching against four buckets: `technical`, `compliance`, `pricing`, `company-info`. The agent re-categorizes implicitly via tool use anyway, so this is just a routing hint.

### Stage 2 — Retrieve  (`retrieve`, no LLM)

**Input:** query string + optional category
**Output:** top-3 KB entries by relevance

Scoring:
- `len(query_terms ∩ entry_terms)` (token overlap)
- `+5` if the query's category matches an entry tag
- Sorted descending; capped at 3 results

Token extraction uses `\w+` so `AES-256-GCM` matches `aes 256 gcm`.

### Stage 3 — Draft  (`draft_answer`, LLM with tool use)

**Input:** question
**Output:** structured answer object

Pseudocode:

```
messages = [user(question)]
for turn in 1..max_turns:
    resp = claude.create(messages, tools=[search_kb])
    if resp.stop_reason == "end_turn":
        return parse_json(resp.text)
    if resp.stop_reason == "tool_use":
        for tool_call in resp:
            result = retrieve(tool_call.input.query, tool_call.input.category)
            tool_results.append(result)
        messages.append(assistant(resp))
        messages.append(user(tool_results))
return {confidence: low, flags: [max_turns_exceeded]}
```

Hard-cap at 5 turns prevents runaway loops. Each turn emits SSE events (`tool_call`, `tool_result`) that the UI shows live.

### Stage 4 — Review  (`review_answers`, LLM, no tools)

**Input:** all drafted answers
**Output:** `{consistency_score, issues, recommendations}`

A second LLM pass that sees all answers as a whole and looks for contradictions only — **not** stylistic notes. The prompt explicitly distinguishes "contradiction" from "out-of-scope omission" to avoid false positives. Robust JSON extractor handles raw JSON, fenced JSON, and JSON embedded in prose.

### Stage 5 — Export  (`export`, no LLM)

**Input:** all of the above
**Output:** single JSON document

```json
{
  "rfp_name": "...",
  "total_questions": 5,
  "answers": [...],
  "review": {...},
  "metadata": {
    "model": "claude-opus-4-7",
    "knowledge_base_entries": 5,
    "generated_at": "2026-..."
  }
}
```

## 3. Event streaming (SSE)

The browser sends one POST and then reads a long-lived stream. Each agent stage emits typed events:

| Event type | Fields | Emitted from |
|---|---|---|
| `pipeline_start` | `rfp_name` | Backend wrapper |
| `stage_start` | `stage` | Each stage entry |
| `question_start` | `qid`, `text`, `category` | Per question |
| `tool_call` | `qid`, `tool`, `input` | Each tool turn |
| `tool_result` | `qid`, `n_results`, `sources` | After tool runs |
| `answer_complete` / `question_done` | `qid`, `answer` | End of draft |
| `stage_done` | `stage`, `questions`/`review`/`final` | Each stage exit |
| `pipeline_complete` | `final` | End of run |
| `error` | `error` | On exception |

Backend uses a `queue.Queue` + producer thread because Flask is synchronous; the generator yields each queued event as `data: {...}\n\n`.

## 4. UI structure

Single page, vanilla JS. Three panels, top-down responsive collapse on narrow viewports.

| Panel | Job |
|---|---|
| **Input** | Textarea + sample loader + parse-only button + run button + optional API key override |
| **Pipeline visualizer** | Four animated cards (`parse → retrieve_draft → review → export`) that pulse when active and turn green when done. Below it, a scrollable activity feed of SSE events |
| **Output** | Tabs for Answers (one card per question, color-coded by confidence), Review (consistency ring + issues/recommendations), Raw JSON |

Confidence colors: high = green, medium = amber, low = red. Source citations are shown as monospace chips.

## 5. File layout

```
ui/
├── agent_core.py        Pipeline stages + KB + LLM glue (also imported by tests)
├── app.py               Flask routes + SSE producer
├── static/
│   ├── index.html       Layout + 3 panels
│   ├── styles.css       Dark theme + stage animations + answer cards
│   └── app.js           Fetch+SSE reader, event dispatcher, renderers
├── tests/
│   ├── conftest.py      Mock Anthropic client + response factories
│   ├── test_parse.py    Parser format detection + edge cases
│   ├── test_retrieve.py KB scoring + empty/missing inputs
│   ├── test_draft.py    Tool loop + JSON extraction + max_turns
│   ├── test_review_export.py  Reviewer parsing + export shape
│   ├── test_pipeline.py End-to-end with mocked LLM
│   └── test_api.py      Flask routes (parse, retrieve, run, sample, kb)
└── ARCHITECTURE.md      This document
```

## 6. Testing strategy

| Layer | What we test | How |
|---|---|---|
| **Stage units** | Each stage's logic in isolation | Direct function calls + asserts |
| **Tool loop** | Multi-turn agent behavior | Mock Anthropic client returning sequenced responses |
| **JSON robustness** | Parser tolerates fences, embedded prose, malformed output | Targeted strings |
| **Pipeline integration** | Stages compose correctly + events fire | `run_pipeline` with mocked client, capture events |
| **HTTP API** | All Flask routes return correct shape + status codes | `app.test_client()` |
| **Event protocol** | UI receives correctly-formatted SSE | Live curl test against running server |
| **End-to-end on real LLM** | The whole thing actually works | Manual via UI; or curl `/api/run` |

55 tests, runs in <0.5s with `pytest tests/`. No real API key or network needed for unit tests — only the live e2e test needs `ANTHROPIC_API_KEY`.

## 7. Failure modes & how they're handled

| Failure | Mitigation |
|---|---|
| LLM returns malformed JSON | `_extract_json` tries fenced + raw + embedded; on failure, returns fallback `{confidence: low, flags: [parse failed]}` |
| Tool loop never ends | `max_turns` (default 5) caps iterations and returns `flags: [max_turns_exceeded]` |
| Reviewer truncates JSON | `max_tokens=4096` (was 1024), plus robust extractor |
| Reviewer flags false positives | Sharpened prompt explicitly enumerates non-contradictions (out-of-scope, scoped distinctions) |
| API key missing | Backend rejects with HTTP 400; UI shows error inline |
| KB has no match | `retrieve` returns empty list; the agent flags low confidence |
| Slow LLM call | UI shows live activity feed so it doesn't look frozen |
| Server thread crash during pipeline | Producer wraps in try/except and emits `{type: error}` over SSE |

## 8. Performance characteristics (measured)

From the 100-trial stability harness on the same KB:

| Metric | Value |
|---|---|
| Median latency per RFP (5 questions + review) | **66s** |
| p95 latency | 980s (rate-limited tail at 6-way concurrency) |
| Tokens per RFP | ~30K input / ~8K output |
| Cost per RFP | ~$0.50 (Opus 4.7) |
| Reviewer `consistency_score = high` | 100/100 runs |
| Trials with 0 reviewer issues | 73/100 |

## 9. What this architecture optimizes for

- **Live feedback over speed** — the UI shows agent activity in real time so users trust it
- **Decoupled stages** — each stage is independently testable, replaceable, and observable
- **Robustness over cleverness** — JSON extractor, max_turns cap, fallback shapes for every failure mode
- **No build step** — vanilla JS, plain HTML, single pip install. `python3 app.py` and you're up.

## 10. What's deliberately out of scope

- Persistence (every run is in-memory; close the tab → lose the result)
- Authentication (single-user assumption; uses server-side env key by default)
- Streaming of the LLM tokens themselves (we stream stage events, not partial text)
- KB editing UI (KB is hardcoded in `agent_core.py`; CRUD endpoints would be a v2)
- Multi-RFP queue / job history
