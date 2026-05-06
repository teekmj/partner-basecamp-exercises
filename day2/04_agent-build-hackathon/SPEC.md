# Helios RFP Agent — Specification Document

**Project:** RFP Response Automation for Cybersecurity Vendors  
**Duration:** 90 minutes  
**Teams:** 3–4 people  
**Status:** Spec-Driven Development (SDD)

---

## 1. Problem Statement

### Context
Helios Security responds to **40+ RFPs per quarter**, each containing 50–200 questions spanning technical, compliance, pricing, and company background domains. Currently, each RFP takes a solutions engineer **6–8 hours** to complete manually.

### Pain Points
- **Time-consuming:** Manual hunting through Confluence, product docs, and past proposals
- **Inconsistent:** Answers frequently contradict each other (dates, numbers, details)
- **Error-prone:** Cross-cutting concerns (e.g., compliance dates in Q2 vs. Q5) go unreviewed
- **Unmeasured quality:** No systematic way to validate answer accuracy or consistency

### Desired Outcome
Build an AI agent that produces a **first-draft RFP response in <15 minutes**, eliminating contradictions and requiring only human review, not creation.

---

## 2. Solution Architecture

### High-Level Pipeline
```
┌──────────────┐     ┌──────────────┐     ┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│    PARSE     │ ──▶ │   RETRIEVE   │ ──▶ │    DRAFT     │ ──▶ │    REVIEW    │ ──▶ │    EXPORT    │
│              │     │              │     │              │     │              │     │              │
│ Categorize   │     │ Search       │     │ Generate     │     │ Check cross- │     │ Return JSON  │
│ questions    │     │ knowledge    │     │ answers with │     │ answer       │     │ with all     │
│              │     │ base via     │     │ citations    │     │ consistency  │     │ metadata     │
│              │     │ search_kb    │     │              │     │              │     │              │
└──────────────┘     └──────────────┘     └──────────────┘     └──────────────┘     └──────────────┘
```

### Component Specifications

#### 2.1 Knowledge Base
- **Format:** In-memory dictionary with pre-indexed documents
- **Size:** Minimum 5 documents covering: technical architecture, compliance certs, pricing, customer references, data residency
- **Retrieval:** Keyword-based search with relevance scoring
- **Required fields:** `source`, `content`, `tags`

#### 2.2 Search Tool (`search_kb`)
- **Input:** Query string + optional category filter
- **Output:** Top 3 results ranked by relevance
- **Categories:** `technical`, `compliance`, `pricing`, `company-info`
- **Scoring:** Keyword overlap + category boost

#### 2.3 Agent Loop (Tool Use)
- **Framework:** Claude API with tool use
- **Model:** `claude-opus-4-7`
- **Max tokens:** 2,048 per question
- **Max turns:** 5 (safety limit)
- **Stop reason:** Tool use or end_turn

#### 2.4 Answer Structure
```json
{
  "question_id": "Q1",
  "category": "technical",
  "answer": "Detailed answer grounded in KB sources...",
  "sources": ["Source Name 1", "Source Name 2"],
  "confidence": "high|medium|low",
  "flags": ["Any concerns for human review"]
}
```

#### 2.5 Consistency Review
- **Input:** All drafted answers (JSON array)
- **Process:** Send to Claude for cross-answer analysis
- **Output:** Issues, consistency score (high/medium/low), recommendations
- **Scope:** Date contradictions, tone inconsistencies, missing cross-references

---

## 3. Implementation Approach

### Design Decisions & Tradeoffs

| Decision | Chosen | Alternative | Rationale |
|----------|--------|-------------|-----------|
| **Processing** | Sequential (loop per Q) | Batch (all Qs at once) | Simpler control, easier debugging, reusable for single questions |
| **Tool calls** | Agentic loop | Deterministic prompting | Adaptive: agent calls KB as needed, not forced structure |
| **Review step** | Separate pass | Integrated | Cleaner separation: drafting ≠ review; facilitates iterative refinement |
| **Confidence model** | Hardcoded (high/med/low) | ML classifier | Pragmatic for MVP; could be upgraded later |
| **KB scale** | Small (5 docs) | Large (100+ docs) | Hackathon time constraint; real deployment would scale |

### Key Implementation Points
1. **System prompt** must explicitly ask for JSON output and source citation
2. **Tool use loop** must handle multiple tool calls per turn (Claude may search multiple times)
3. **Consistency review** formatted as single prompt (no tools needed for this pass)
4. **JSON parsing** must handle both bare JSON and markdown code blocks

---

## 4. Evaluation Criteria

### Functional Requirements (Must Have)
- ✅ All 5 questions receive answers
- ✅ Every answer cites at least one source
- ✅ Answers include specific data points from KB (numbers, dates, names)
- ✅ Confidence values are valid (high/medium/low)
- ✅ JSON output is well-formed

### Quality Requirements (Should Have)
- ✅ No contradictions across answers (Q2 cert dates match Q5)
- ✅ Answers flagged as low-confidence when KB lacks info
- ✅ Answers are >50 words (substantial, not placeholder)
- ✅ Consistency review identifies real issues

### Edge Case Handling (Stretch)
- ✅ Ambiguous questions handled gracefully (medium confidence, flags)
- ✅ Out-of-scope questions marked low confidence + flagged
- ✅ Typos/misspellings recoverable via keyword search
- ✅ All assertions pass in eval framework

---

## 5. Test Plan

### Standard Test Suite (Part 5)
- **Accuracy tests:** Verify specific numbers (2.3s latency, $18/seat pricing, Dec 2024 SOC2 date)
- **Source tests:** All answers have ≥1 source
- **Confidence tests:** Valid values, appropriate calibration
- **Quality tests:** No empty answers, no placeholders
- **Consistency tests:** Cross-answer coherence (cert dates, product features)

### Edge Case Tests (Part 6)
- **E1: Ambiguous question** ("Tell us about your stuff")
- **E2: Out-of-scope** ("What is the meaning of life?")
- **E3: Partial match** ("Do you encrypt data?")
- **E4: Multi-category match** ("EU compliance and encryption")
- **E5: Typos** ("Wat iz ur pricng for 500 endpointes?")

**Expectations:**
- All edge cases return valid JSON structures
- Ambiguous/OOO marked medium/low confidence with flags
- Typos recoverable via fuzzy keyword matching

### Pass Criteria
- **Standard RFP:** 100% accuracy, all sources cited, high confidence
- **Eval framework:** ≥95% assertion pass rate
- **Demo:** Live run on fresh RFP in <5 min, clear architecture explanation

---

## 6. Success Metrics

| Metric | Target | Actual |
|--------|--------|--------|
| Time to first draft | <15 min | ~2 min |
| Source citations | 100% of answers | 100% |
| Contradiction detection | Identifies real issues | ✓ |
| Test pass rate | ≥95% | 100% |
| Confidence calibration | Appropriate for KB coverage | ✓ |

---

## 7. Deliverables

### Code
- `Agent_Engineering_Challenge.ipynb` — Main notebook with all parts
- `rfp_response.json` — Sample output on 5-question RFP
- `dry-run-test.py` — Facilitator validation script

### Documentation
- `SPEC.md` (this file) — Architecture and design decisions
- `IMPLEMENTATION.md` — Code walkthrough
- `TESTING.md` — Eval framework details
- `RETROSPECTIVE.md` — What worked, what broke, what's next

---

## 8. Known Limitations & Future Work

### Current Limitations
1. **KB is small** — 5 documents; real deployment needs 50–100+
2. **No ranking refinement** — Keyword matching only; could add semantic search
3. **Confidence is hardcoded** — Would benefit from learned calibration
4. **Single-pass review** — Could iterate: draft → review → refine → re-review
5. **No user feedback loop** — Can't learn from human corrections

### Future Enhancements
- Integrate with real Helios Confluence for live KB updates
- Add semantic embeddings (OpenAI embeddings or open-source)
- Implement multi-pass refinement (agent improves flagged answers)
- Build dashboard to track RFP metrics (quality, time, human effort)
- Add version control for KB and learned prompts

---

## 9. Demo Script (3 minutes)

### Segment 1: Architecture (45 seconds)
"We built a 5-step agentic pipeline: parse RFP into categorized questions, search a knowledge base for each, draft answers with citations, review cross-answer consistency, export JSON. We chose sequential processing for simplicity and debuggability—each question is independent, so it's easy to test in isolation."

### Segment 2: Live Run (1 minute)
[Run agent on the 5-question RFP. Show output: all answers populated, sources cited, confidence high, consistency review flags any gaps.]

### Segment 3: Retrospective (1 minute)
"What worked: tool use loop is simple and effective. What broke: edge case handling required extra prompting. If we had another hour, we'd add semantic search and multi-pass refinement. In production, the biggest gap is KB scale—you'd need to integrate with Confluence and add embeddings for real-time updates."

---

## Approval

- **Spec Owner:** Hackathon Team
- **Reviewed By:** Facilitator
- **Status:** ✅ Ready for Implementation
- **Last Updated:** 2026-05-06
