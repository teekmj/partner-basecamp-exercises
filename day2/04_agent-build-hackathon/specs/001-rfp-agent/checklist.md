# Spec Validation Checklist: RFP Response Automation Agent

**Purpose**: Validate that the implementation in `Agent_Engineering_Challenge.ipynb` satisfies every functional requirement and success criterion in `spec.md`.
**Created**: 2026-05-06
**Feature**: [spec.md](spec.md)

## Drafting Requirements (FR-1xx)

- [x] CHK101 FR-101 — Verify `process_rfp` accepts list of `{id, category, text}` dicts
- [x] CHK102 FR-102 — Verify `search_kb` tool is registered and called during drafting
- [x] CHK103 FR-103 — Verify one answer object per input question, IDs preserved
- [x] CHK104 FR-104 — Verify every answer has all six required fields
- [x] CHK105 FR-105 — Verify `confidence` is one of `high`/`medium`/`low` for every answer
- [x] CHK106 FR-106 — Verify `sources` is a non-empty list of strings
- [x] CHK107 FR-107 — Verify tool-use loop has a `max_turns` bound (currently 5)

## Review Requirements (FR-2xx)

- [x] CHK201 FR-201 — Verify `review_answers` takes a list and returns a single dict
- [x] CHK202 FR-202 — Verify review output has `consistency_score`, `issues`, `recommendations`
- [x] CHK203 FR-203 — Verify `consistency_score` is `high`/`medium`/`low`
- [x] CHK204 FR-204 — Verify review uses a separate `client.messages.create` call
- [x] CHK205 FR-205 — Verify review handles malformed JSON without crashing

## Export Requirements (FR-3xx)

- [x] CHK301 FR-301 — Verify final JSON has all 5 top-level fields
- [x] CHK302 FR-302 — Verify metadata includes model name and KB entry count

## Evaluation Requirements (FR-4xx)

- [x] CHK401 FR-401 — Verify `ComprehensiveEval` class exists and runs
- [x] CHK402 FR-402 — Verify `assert_has_sources` is called for each question
- [x] CHK403 FR-403 — Verify `assert_confidence_valid` is called for each question
- [x] CHK404 FR-404 — Verify factual data-point assertions exist (latency, dates, pricing, etc.)
- [x] CHK405 FR-405 — Verify fuzzy matching is used (`assert_matches_any` or `_normalize`)
- [x] CHK406 FR-406 — Verify `assert_consistent_across` is conditional on multiple mentions
- [x] CHK407 FR-407 — Verify `print_summary` outputs total/passed/failed/pass rate

## Success Criteria (SC-xxx)

- [x] CHK501 SC-001 — End-to-end execution completes in under 3 minutes
- [x] CHK502 SC-002 — 100% of answers cite at least one source
- [x] CHK503 SC-003 — 100% of answers have valid confidence values
- [x] CHK504 SC-004 — ≥ 90% of factual data points present in answers
- [x] CHK505 SC-005 — Review step returns parseable report (no parse_error)
- [x] CHK506 SC-006 — Eval framework pass rate ≥ 95%
- [x] CHK507 SC-007 — Notebook executes with zero cell errors

## Edge Case Handling

- [x] CHK601 Out-of-scope question handled (low confidence + flags)
- [x] CHK602 Ambiguous question handled gracefully
- [x] CHK603 Question with typos still resolves to correct KB entry
- [x] CHK604 Tool-use loop terminates within `max_turns`
- [x] CHK605 Malformed JSON parse returns fallback structure
- [x] CHK606 LLM rephrasing tolerated by fuzzy match
- [x] CHK607 Single-mention data points don't trigger false-positive consistency flags

## Specialist sub-agents (FR-15x)

- [x] CHK150 Four drafting specialists + two post-draft (reviewer, demoer) defined
- [x] CHK151 Each specialist is a `claude_agent_sdk.AgentDefinition` with distinct prompt
- [x] CHK152 Default category routing wired (technical→architect, etc.)
- [x] CHK153 Drafted answers carry `specialist_key` and `specialist_label`
- [x] CHK154 `specialist_assigned` SSE event emitted on routing
- [x] CHK155 `use_specialists=False` falls back to generic system prompt
- [ ] CHK156 Reviewer scores 4 dimensions + emits verdict
- [ ] CHK157 Demoer produces both client_pitch object + AE speaker notes
- [ ] CHK158 Exported HTML renders "Why Helios" before answers; AE notes after, labeled internal

## Parallel execution (FR-16x)

- [ ] CHK160 Drafting runs in parallel by default (4 workers)
- [ ] CHK161 `parallel=False` opt-out works

## Eval persistence (FR-408 / FR-409)

- [x] CHK408 Each eval run appears in BOTH live log and durable archive
- [x] CHK409 `GET /api/evals/archive` returns archived runs

## Scenario corpus (FR-5xx)

- [x] CHK501 50 seed scenarios installed, ≥6 verticals, ≥12 clients
- [x] CHK502 Every seed has 3–6 questions, ≥2 distinct categories
- [x] CHK503 Re-seeding is idempotent (no duplicates by `seed-NNN` ID)
- [x] CHK504 Auto-seed runs on first startup when store is empty
- [x] CHK505 `POST /api/scenarios/seed` endpoint exists and is idempotent

## Notes

- Items checked off as `[x]` once verified by automated validation
- Failures are logged with line references and remediation needed
- This file is regenerated each validation run
