# Feature Specification: RFP Response Automation Agent

**Feature Branch**: `001-rfp-agent`
**Created**: 2026-05-06
**Status**: Implemented
**Input**: AI Engineering Lab Hackathon - Agent Build Challenge: automate RFP response drafting for Helios Security

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Draft answers for an RFP questionnaire (Priority: P1)

A solutions engineer at Helios Security receives a prospect RFP with 5–200 questions across technical, compliance, pricing, and company-info categories. They paste the questionnaire into the agent and receive a draft response document with answers grounded in Helios source material — typically in under 15 minutes vs. the 6–8 hours of manual hunting through Confluence.

**Why this priority**: This is the core value proposition. Without it, the agent has no purpose. P1 because it must work end-to-end before any other capability is meaningful.

**Independent Test**: Provide the 5-question sample RFP. Verify the agent returns a JSON list of 5 answer objects, each with a non-empty answer, at least one source citation, and a confidence rating.

**Acceptance Scenarios**:

1. **Given** a list of 5 RFP questions across 4 categories, **When** the agent processes the questionnaire, **Then** it returns 5 structured answer objects with the same question IDs.
2. **Given** a question whose answer is fully covered by the knowledge base, **When** the agent answers, **Then** confidence is `high` and at least one source is cited.
3. **Given** a question that requires specific quantitative data (e.g., latency, pricing), **When** the agent answers, **Then** the exact figure from the source material appears in the answer.

---

### User Story 2 - Catch cross-answer inconsistencies (Priority: P1)

The customer (Helios) explicitly identified cross-answer contradictions as the #1 quality issue in manual responses. The agent must holistically review the drafted answers and flag any contradictions in dates, numbers, or claims so a human reviewer can reconcile them before sending.

**Why this priority**: Without this step, the agent produces answers no better than a junior engineer copy-pasting from Confluence. The review step is what makes the output trustworthy. P1 because it is a stated customer requirement.

**Independent Test**: After drafting all answers, run the review step and verify it returns a structured report with `consistency_score`, `issues`, and `recommendations` fields.

**Acceptance Scenarios**:

1. **Given** five drafted answers, **When** the review step runs, **Then** it returns a JSON object with a consistency score of `high`, `medium`, or `low`.
2. **Given** answers that share a referenced data point (e.g., SOC 2 audit date), **When** the data points disagree, **Then** the review flags this as an issue.
3. **Given** answers that are internally consistent, **When** the review runs, **Then** the score is `high` and the issues list may still contain stylistic or coverage observations but no contradictions.

---

### User Story 3 - Export structured deliverable (Priority: P2)

A downstream system (or human reviewer) needs to consume the agent's output as machine-readable JSON to populate a final response document or feed an approval workflow.

**Why this priority**: Required for integration but secondary to the drafting and review steps. P2 because export format is a packaging concern, not a content correctness concern.

**Independent Test**: After running the pipeline, verify the final output is valid JSON containing the RFP name, total questions, answers list, review object, and metadata.

**Acceptance Scenarios**:

1. **Given** completed answers and review, **When** the export step runs, **Then** the output is a single JSON object that parses successfully and contains all required top-level fields.

---

### Edge Cases

- **Question outside the knowledge base**: Agent should answer with `confidence: "low"` and populate `flags` with a clear note rather than hallucinating.
- **Ambiguous question** (e.g., "Tell us about your stuff"): Agent should still produce a structured response, mark confidence as `low` or `medium`, and flag the ambiguity.
- **Question with typos** (e.g., "Wat iz ur pricng for 500 endpointes?"): Agent should still match relevant KB entries and answer correctly.
- **Long-running tool loop**: Agent must terminate within a finite number of turns and not loop indefinitely.
- **LLM returns malformed JSON**: Parser must fail gracefully and surface the raw response rather than crashing.
- **LLM rephrases data points** (e.g., `$18/seat/month` → `$18 per seat per month`): Eval framework must use fuzzy matching, not exact string comparison.
- **Cross-question consistency check when only one answer mentions a data point**: Should not flag this as an inconsistency — there is nothing to be inconsistent with.

## Requirements *(mandatory)*

### Functional Requirements

#### Drafting (FR-1xx)

- **FR-101**: System MUST accept a list of question objects, each containing `id`, `category`, and `text`.
- **FR-102**: System MUST search a knowledge base via a tool call (`search_kb`) before drafting each answer.
- **FR-103**: System MUST return one structured answer object per input question with the same `question_id`.
- **FR-104**: Each answer object MUST contain `question_id`, `category`, `answer`, `sources`, `confidence`, and `flags` fields.
- **FR-105**: `confidence` MUST be one of: `high`, `medium`, `low`.
- **FR-106**: `sources` MUST be a list of source names taken from KB entries used to answer.
- **FR-107**: System MUST terminate the tool-use loop within a bounded number of turns (default: 5).

#### Specialist sub-agents (FR-15x) — added 2026-05-06

- **FR-150**: System MUST define four drafting sub-agents (`architect`, `pricing_lead`, `compliance`, `business_sme`) AND two post-draft sub-agents (`reviewer`, `demoer`). Each MUST have a distinct system prompt reflecting its role.
- **FR-151**: Specialists MUST be configured using the Claude Agent SDK's `AgentDefinition` schema (description, prompt, tools, model, maxTurns).
- **FR-152**: System MUST route each question to a drafting specialist. Default routing is by category (`technical → architect`, `pricing → pricing_lead`, `compliance → compliance`, `company-info → business_sme`). Unknown categories fall back to keyword-based routing.
- **FR-153**: Drafted answers MUST include `specialist_key` and `specialist_label` fields so consumers know which sub-agent handled the question.
- **FR-154**: A `specialist_assigned` SSE event MUST be emitted when a question is routed to a specialist, carrying `qid`, `specialist_key`, and `specialist_label`.
- **FR-155**: Specialist routing MUST be opt-in via the `use_specialists` parameter (default `True`). Disabling it MUST fall back to the generic system prompt.
- **FR-156**: After drafting, the `reviewer` sub-agent MUST score the response on four dimensions (`accuracy`, `completeness`, `cite_quality`, `tone_consistency`, each 0–10) and emit a verdict (`ship` / `revise_minor` / `revise_major`).
- **FR-157**: After drafting, the `demoer` sub-agent MUST produce a presenter package containing BOTH:
  - A `client_pitch` object with `headline`, `why_helios` (3-paragraph narrative tailored to the prospect's questions), `value_pillars` (≥3), and `tailored_to`.
  - Speaker notes for the AE: `elevator_pitch`, `top_talking_points`, `key_differentiators`, `likely_followups`, `call_to_action`.
- **FR-158**: The exported HTML deliverable MUST render the `client_pitch` as a prominent "Why Helios" section after the executive summary and before the drafted answers. AE speaker notes MUST appear AFTER the answers and be visibly labeled "Internal use only".

#### Parallel execution (FR-16x)

- **FR-160**: System MUST support drafting questions in parallel via a thread pool (default `parallelism=4`).
- **FR-161**: Parallel mode MUST be opt-out via the `parallel` flag on the run endpoint (default `True`).

#### Review (FR-2xx)

- **FR-201**: System MUST accept the full list of drafted answers and return a single review report.
- **FR-202**: Review report MUST contain `consistency_score`, `issues`, and `recommendations`.
- **FR-203**: `consistency_score` MUST be one of: `high`, `medium`, `low`.
- **FR-204**: Review MUST be performed in a separate model call from drafting (so it sees all answers as a whole).
- **FR-205**: Review MUST gracefully handle malformed model output by returning a fallback object rather than raising.

#### Export (FR-3xx)

- **FR-301**: Final output MUST be valid JSON containing `rfp_name`, `total_questions`, `answers`, `review`, and `metadata` fields.
- **FR-302**: `metadata` MUST include the model name and number of knowledge base entries used.

#### Evaluation (FR-4xx)

- **FR-401**: An eval framework MUST exist that runs assertions against the agent's output.
- **FR-402**: Eval MUST verify each answer has at least one source citation.
- **FR-403**: Eval MUST verify each answer's confidence is a valid value.
- **FR-404**: Eval MUST verify factual accuracy by checking specific data points (e.g., `2.3 second` for Q1 latency).
- **FR-405**: Eval MUST tolerate LLM phrasing variation through fuzzy matching (e.g., `/` ≡ `per`, whitespace normalization).
- **FR-406**: Cross-question consistency assertions MUST be conditional — they only apply if multiple answers mention the same data point.
- **FR-407**: Eval framework MUST report total tests, passes, failures, and pass rate.
- **FR-408**: Every eval run MUST be persisted to BOTH the live log (`data/eval_runs.jsonl`, mutable) AND the durable archive (`data/evals_archive/<YYYY-MM-DD>.jsonl`, append-only, committed).
- **FR-409**: The archive MUST be readable via `GET /api/evals/archive` so historical pass rates can be tracked across deployments.

#### Scenario corpus (FR-5xx)

- **FR-501**: System MUST ship with a corpus of 50 pre-built sample scenarios spanning at least 6 verticals (banking, insurance, healthcare, retail, public sector, fintech) and at least 12 fictional clients.
- **FR-502**: Each seed scenario MUST contain 3–6 questions drawn from a diverse bank, with at least 2 distinct categories represented.
- **FR-503**: Seeding MUST be idempotent: re-running `seed_scenarios.seed()` MUST NOT duplicate existing seed scenarios (matched by `seed-NNN` ID prefix).
- **FR-504**: Seeding MUST run automatically on first server startup if the scenario store is empty.
- **FR-505**: System MUST expose a `POST /api/scenarios/seed` endpoint to re-seed on demand.

### Key Entities

- **Question**: An RFP item to be answered. Attributes: `id`, `category`, `text`.
- **Answer**: A structured response to one question. Attributes: `question_id`, `category`, `answer`, `sources`, `confidence`, `flags`.
- **KnowledgeBase Entry**: A retrievable document. Attributes: `id`, `source`, `content`, `tags`.
- **Review Report**: The output of the consistency review step. Attributes: `consistency_score`, `issues`, `recommendations`.
- **Eval Result**: One assertion's outcome. Attributes: `test`, `question`, `passed`, `details`.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: An RFP of 5 questions is drafted, reviewed, and exported in under 3 minutes wall-clock time.
- **SC-002**: 100% of drafted answers cite at least one source.
- **SC-003**: 100% of drafted answers have a valid confidence value (`high`/`medium`/`low`).
- **SC-004**: ≥ 90% of drafted answers contain the specific factual data points expected for their question (e.g., `2.3 seconds` for Q1, `AES-256-GCM` for Q5).
- **SC-005**: The review step returns a parseable structured report with no parse errors on a fresh run.
- **SC-006**: Eval framework achieves ≥ 95% pass rate on a fresh notebook execution.
- **SC-007**: End-to-end notebook execution completes with zero cell errors.

## Assumptions

- Anthropic API is reachable and a valid API key is provided in the environment.
- The knowledge base is hardcoded for the hackathon scope (5 entries) — no external KB is required.
- The agent uses `claude-opus-4-7` for both drafting and review (current production model).
- Sequential question processing is acceptable; batch processing is a future optimization.
- Output is consumed by a downstream human reviewer who will approve or revise before sending to the prospect.
- The 5-question sample RFP is representative; the same patterns scale to longer questionnaires.
- **Specialist sub-agents** are configured using `claude_agent_sdk.AgentDefinition` as the source-of-truth schema. The Messages API is invoked directly (rather than the SDK's CLI-driven `query()` flow) because the platform is a long-running Flask server, not a CLI session.
- The seed corpus uses fictional clients; any resemblance to real organizations is coincidental.
