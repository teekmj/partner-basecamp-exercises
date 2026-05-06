"""Agent core: pipeline stages exposed as composable functions.

Stages: parse → retrieve → draft → review → export
Each stage is independently testable. The Flask app glues them together
and emits Server-Sent Events between stages for live UI updates.
"""

from __future__ import annotations

import json
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable, Iterable, Optional

import anthropic

# ============================================================
# Knowledge Base (mirrors notebook KB)
# ============================================================

KNOWLEDGE_BASE: dict[str, dict] = {
    "threat_detection": {
        "source": "Helios Platform Architecture Doc v4.2",
        "content": (
            "Helios Sentinel uses signature-based, behavioral, and ML detection. "
            "Latency: 2.3s signatures, 18s behavioral. The base EPP+EDR platform includes "
            "a built-in correlation engine processing 50,000 EPS per tenant. The full "
            "Helios SIEM module — third-party log ingestion, custom rules, long-term log "
            "retention — is sold as a separate add-on (see pricing)."
        ),
        "tags": ["technical", "detection", "latency"],
    },
    "compliance_certs": {
        "source": "Helios Compliance Register 2025",
        "content": (
            "SOC 2 Type II Dec 2024 (Deloitte), ISO 27001:2022 Mar 2024 (BSI), "
            "FedRAMP Moderate Jun 2024 (DHS), PCI DSS v4.0 Sep 2024 (Coalfire), "
            "HIPAA Oct 2024, StateRAMP Jan 2025."
        ),
        "tags": ["compliance", "certifications", "audit"],
    },
    "pricing_model": {
        "source": "Helios Pricing Sheet Q1 2025",
        "content": (
            "EPP+EDR bundle (includes built-in correlation engine): "
            "500 EP $18/seat/mo; 1,000 EP $15/seat/mo (17% off); 5,000 EP $11/seat/mo (39% off). "
            "Mid-tier endpoint counts price at the next-lower-tier rate. "
            "Min term 12 months. 2yr +5%, 3yr +10%. "
            "Full SIEM add-on +$6/seat/mo. MDR +$12/seat/mo."
        ),
        "tags": ["pricing", "commercial"],
    },
    "financial_services_customers": {
        "source": "Helios Vertical Report 2024",
        "content": (
            "47 customers in financial services (12 banks, 8 insurance, 15 asset mgmt, 12 fintech). "
            "References: Meridian National (3,200 EP, 2022), Crestview Capital (850 EP, 2023), "
            "Apex Insurance (5,100 EP, 2021). NPS 72."
        ),
        "tags": ["company-info", "customers"],
    },
    "data_residency_eu": {
        "source": "Helios Data Sovereignty v3.1",
        "content": (
            "EU residency: Frankfurt + Dublin. AES-256-GCM at rest. "
            "TLS 1.3 in transit with cert pinning. GDPR DPA. NCC Group annual pentest. "
            "Retention 90d telemetry / 13mo alerts."
        ),
        "tags": ["technical", "compliance", "eu", "encryption"],
    },
}


# ============================================================
# Stage 1: PARSE — turn raw input into structured questions
# ============================================================

CATEGORY_HINTS = {
    "technical": ["latency", "detection", "encryption", "architecture", "data", "throughput", "ingest", "endpoint", "platform"],
    "compliance": ["soc", "iso", "fedramp", "hipaa", "pci", "audit", "certification", "compliant", "gdpr"],
    "pricing": ["price", "pricing", "cost", "discount", "contract", "seat", "license", "term"],
    "company-info": ["customer", "reference", "vertical", "history", "team", "headcount", "nps"],
}


def parse_questionnaire(raw_text: str) -> list[dict]:
    """Split a raw questionnaire into a list of {id, category, text} dicts.

    Accepts:
      - JSON list: [{"id": "Q1", "category": "...", "text": "..."}, ...]
      - Numbered/bulleted text: each line or paragraph becomes a question
    """
    raw_text = (raw_text or "").strip()
    if not raw_text:
        return []

    # Try JSON list first
    if raw_text.startswith("["):
        try:
            data = json.loads(raw_text)
            if isinstance(data, list):
                return [_normalize_question(q, i) for i, q in enumerate(data)]
        except json.JSONDecodeError:
            pass  # fall through

    # Otherwise: split on lines that look like Q1./1./- markers, or blank lines
    chunks = re.split(r"\n\s*\n", raw_text)
    if len(chunks) < 2:
        # Try line-by-line if no double-blank separators
        chunks = [c for c in raw_text.split("\n") if c.strip()]

    questions: list[dict] = []
    for i, chunk in enumerate(chunks, start=1):
        text = chunk.strip()
        # Strip leading numbering like "Q1.", "1.", "1)", "-"
        text = re.sub(r"^(?:Q?\d+[.)\]:]\s*|[-•*]\s*)", "", text)
        if not text:
            continue
        questions.append({
            "id": f"Q{i}",
            "category": _infer_category(text),
            "text": text,
        })

    return questions


def _normalize_question(q: dict, idx: int) -> dict:
    return {
        "id": q.get("id") or f"Q{idx + 1}",
        "category": q.get("category") or _infer_category(q.get("text", "")),
        "text": q.get("text", "").strip(),
    }


def _infer_category(text: str) -> str:
    """Heuristic: count keyword hits per category, return the winner."""
    t = text.lower()
    scores = {cat: sum(1 for kw in kws if kw in t) for cat, kws in CATEGORY_HINTS.items()}
    best_cat, best_score = max(scores.items(), key=lambda kv: kv[1])
    return best_cat if best_score > 0 else "technical"


# ============================================================
# Stage 2: RETRIEVE — search the KB
# ============================================================

def retrieve(query: str, category: Optional[str] = None, kb: Optional[dict] = None) -> list[dict]:
    """Score KB entries by keyword overlap; boost on category match."""
    kb = kb if kb is not None else KNOWLEDGE_BASE
    query_terms = set(re.findall(r"\w+", query.lower()))
    if not query_terms:
        return []

    results = []
    for entry_id, entry in kb.items():
        entry_text = (entry["content"] + " " + " ".join(entry["tags"])).lower()
        entry_tokens = set(re.findall(r"\w+", entry_text))
        overlap = len(query_terms & entry_tokens)
        if category and category.lower() in [t.lower() for t in entry["tags"]]:
            overlap += 5
        if overlap > 0:
            results.append({
                "id": entry_id,
                "source": entry["source"],
                "content": entry["content"],
                "relevance_score": overlap,
            })
    results.sort(key=lambda x: x["relevance_score"], reverse=True)
    return results[:3]


# ============================================================
# Stage 3: DRAFT — call LLM with tool use
# ============================================================

SEARCH_KB_TOOL = {
    "name": "search_kb",
    "description": "Search Helios knowledge base for RFP-relevant information",
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {"type": "string"},
            "category": {
                "type": "string",
                "enum": ["technical", "compliance", "pricing", "company-info"],
            },
        },
        "required": ["query"],
    },
}

SYSTEM_PROMPT = """You are an AI assistant helping Helios Security respond to RFP questionnaires.

For each question:
1. Use search_kb to find relevant source material
2. Draft a polished, cited answer
3. Cite sources by name
4. Flag low-confidence answers
5. When the KB distinguishes a built-in capability from a paid add-on, preserve that distinction precisely
6. When citing pricing, explain non-standard endpoint counts if the KB describes a rule

Return JSON: {"question_id": "...", "category": "...", "answer": "...", "sources": [...], "confidence": "high|medium|low", "flags": [...]}"""


# Specialist routing is opt-in. When a specialist is provided, its prompt
# replaces the default SYSTEM_PROMPT for that draft call.
try:
    from specialists import get_specialist, pick_specialist, SPECIALIST_LABELS
    SPECIALISTS_AVAILABLE = True
except ImportError:
    SPECIALISTS_AVAILABLE = False


def _repair_json_strings(text: str) -> str:
    """Escape literal control characters that appear inside JSON string
    values (a common LLM pitfall — Opus often emits raw newlines inside
    long string values rather than the required ``\\n`` escape).

    Walks the text char-by-char, tracking whether we're inside a quoted
    string with proper backslash-escape handling. Outside strings, control
    chars are left alone.
    """
    out: list[str] = []
    in_string = False
    escape_next = False
    for ch in text:
        if escape_next:
            out.append(ch)
            escape_next = False
            continue
        if ch == "\\":
            out.append(ch)
            escape_next = True
            continue
        if ch == '"':
            in_string = not in_string
            out.append(ch)
            continue
        if in_string:
            if ch == "\n":
                out.append("\\n")
                continue
            if ch == "\r":
                out.append("\\r")
                continue
            if ch == "\t":
                out.append("\\t")
                continue
        out.append(ch)
    return "".join(out)


def _extract_json(text: str) -> dict:
    """Robust JSON extractor.

    Order of attempts:
      1. Strip markdown fences if present.
      2. Slice from first ``{`` to last ``}``.
      3. ``json.loads`` directly.
      4. On failure: repair unescaped control chars inside strings, retry.
    """
    text = text.strip()
    if "```json" in text:
        text = text.split("```json", 1)[1].split("```", 1)[0]
    elif "```" in text:
        text = text.split("```", 1)[1].split("```", 1)[0]
    s, e = text.find("{"), text.rfind("}")
    if s != -1 and e > s:
        text = text[s : e + 1]
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return json.loads(_repair_json_strings(text))


def draft_answer(
    client: anthropic.Anthropic,
    qid: str,
    qtext: str,
    category: str,
    on_event: Optional[Callable[[dict], None]] = None,
    model: str = "claude-opus-4-7",
    max_turns: int = 5,
    use_specialists: bool = True,
) -> dict:
    """Run the agent's tool-use loop for a single question.

    If use_specialists=True (default), routes the question to one of four
    specialist sub-agents (architect / pricing_lead / compliance / business_sme)
    based on category, swapping in their custom system prompt.

    Calls on_event for each loop turn (tool call, tool result, final answer)
    so the UI can stream agent activity.
    """
    # Pick specialist (or fall back to generic SYSTEM_PROMPT)
    system_prompt = SYSTEM_PROMPT
    specialist_key = None
    specialist_label = None
    if use_specialists and SPECIALISTS_AVAILABLE:
        specialist_key = pick_specialist(category, qtext)
        spec = get_specialist(specialist_key)
        system_prompt = spec.prompt
        model = spec.model or model
        max_turns = spec.maxTurns or max_turns
        specialist_label = SPECIALIST_LABELS.get(specialist_key, specialist_key)
        if on_event:
            on_event({
                "type": "specialist_assigned",
                "qid": qid,
                "specialist_key": specialist_key,
                "specialist_label": specialist_label,
            })

    messages = [{"role": "user", "content": f"ID: {qid}, Category: {category}\nQuestion: {qtext}"}]

    for turn in range(max_turns):
        resp = client.messages.create(
            model=model,
            max_tokens=2048,
            system=system_prompt,
            messages=messages,
            tools=[SEARCH_KB_TOOL],
        )

        if resp.stop_reason == "end_turn":
            for block in resp.content:
                if block.type == "text":
                    try:
                        parsed = _extract_json(block.text)
                        if specialist_key:
                            parsed["specialist_key"] = specialist_key
                            parsed["specialist_label"] = specialist_label
                        if on_event:
                            on_event({"type": "answer_complete", "qid": qid, "answer": parsed})
                        return parsed
                    except (json.JSONDecodeError, ValueError):
                        fallback = {
                            "question_id": qid,
                            "category": category,
                            "answer": block.text,
                            "sources": [],
                            "confidence": "low",
                            "flags": ["JSON parse failed"],
                        }
                        if specialist_key:
                            fallback["specialist_key"] = specialist_key
                            fallback["specialist_label"] = specialist_label
                        return fallback
            break

        if resp.stop_reason == "tool_use":
            messages.append({"role": "assistant", "content": resp.content})
            tool_results = []
            for block in resp.content:
                if block.type == "tool_use":
                    if on_event:
                        on_event({"type": "tool_call", "qid": qid, "tool": block.name, "input": block.input})
                    if block.name == "search_kb":
                        result = retrieve(block.input["query"], block.input.get("category"))
                        if on_event:
                            on_event({"type": "tool_result", "qid": qid, "n_results": len(result), "sources": [r["source"] for r in result]})
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": json.dumps(result),
                        })
                    else:
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": json.dumps({"error": "unknown tool"}),
                        })
            messages.append({"role": "user", "content": tool_results})

    fallback = {
        "question_id": qid,
        "category": category,
        "answer": "Max turns reached without completion.",
        "sources": [],
        "confidence": "low",
        "flags": ["max_turns_exceeded"],
    }
    if specialist_key:
        fallback["specialist_key"] = specialist_key
        fallback["specialist_label"] = specialist_label
    return fallback


# ============================================================
# Stage 4: REVIEW — cross-question consistency
# ============================================================

REVIEW_PROMPT_TMPL = """Review these RFP answers for cross-question consistency.

Answers:
{answers}

Flag an item ONLY if it is a genuine contradiction or factual error a prospect would catch.

1. CONTRADICTION = same fact stated differently across answers (e.g., "SOC 2 audited Dec 2024" vs "Nov 2024"). FLAG.
2. NOT a contradiction = same word at different scopes the answers explicitly distinguish. DO NOT FLAG.
3. NOT a contradiction = topic mentioned in one answer but not another when out of the second's scope. DO NOT FLAG.
4. Tone differences only flag if extreme.

Return JSON: {{"issues": [], "consistency_score": "high|medium|low", "recommendations": []}}

If no genuine contradictions, set consistency_score to "high" and return empty issues. Limit to at most 5 items each."""


def review_answers(
    client: anthropic.Anthropic,
    answers: list[dict],
    model: str = "claude-opus-4-7",
) -> dict:
    prompt = REVIEW_PROMPT_TMPL.format(answers=json.dumps(answers, indent=2))
    resp = client.messages.create(
        model=model,
        max_tokens=4096,
        messages=[{"role": "user", "content": prompt}],
    )
    text = resp.content[0].text
    try:
        return _extract_json(text)
    except (json.JSONDecodeError, ValueError) as e:
        return {
            "raw_response": text,
            "parse_error": str(e),
            "consistency_score": "unknown",
            "issues": [],
            "recommendations": [],
        }


# ============================================================
# Stage 5: EXPORT — final deliverable
# ============================================================

def export(rfp_name: str, questions: list[dict], answers: list[dict], review: dict,
           model: str, qa_review: dict | None = None, demo_script: dict | None = None) -> dict:
    out = {
        "rfp_name": rfp_name,
        "total_questions": len(questions),
        "answers": answers,
        "review": review,
        "metadata": {
            "model": model,
            "knowledge_base_entries": len(KNOWLEDGE_BASE),
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        },
    }
    if qa_review is not None:
        out["qa_review"] = qa_review
    if demo_script is not None:
        out["demo_script"] = demo_script
    return out


# ============================================================
# Reviewer specialist (FR-15x post-draft)
# ============================================================

def review_quality(client: anthropic.Anthropic, answers: list[dict]) -> dict:
    """Senior Reviewer: scores answers across 4 dimensions, returns verdict."""
    if not SPECIALISTS_AVAILABLE:
        return {"error": "specialists not available"}
    from specialists import get_specialist
    spec = get_specialist("reviewer")

    prompt = (
        "Review these RFP answers and grade them per your scoring rubric.\n\n"
        "Answers:\n"
        f"{json.dumps(answers, indent=2)}"
    )
    resp = client.messages.create(
        model=spec.model or "claude-opus-4-7",
        max_tokens=4096,
        system=spec.prompt,
        messages=[{"role": "user", "content": prompt}],
    )
    text = resp.content[0].text
    truncated = getattr(resp, "stop_reason", None) == "max_tokens"
    try:
        parsed = _extract_json(text)
        # Compute overall if not provided
        if "overall" not in parsed and "scores" in parsed:
            scores = parsed["scores"]
            if scores:
                parsed["overall"] = round(sum(scores.values()) / len(scores), 1)
        return parsed
    except (json.JSONDecodeError, ValueError) as e:
        return {
            "raw_response": text,
            "parse_error": ("response_truncated" if truncated else str(e)),
            "scores": {},
            "verdict": "unknown",
            "summary": "(review unavailable)",
            "top_issues": [],
            "strengths": [],
        }


# ============================================================
# Demoer specialist (FR-15x post-draft)
# ============================================================

def generate_demo_script(client: anthropic.Anthropic, answers: list[dict],
                         scenario: dict | None = None) -> dict:
    """Sales Engineering Lead: turns answers into presenter script."""
    if not SPECIALISTS_AVAILABLE:
        return {"error": "specialists not available"}
    from specialists import get_specialist
    spec = get_specialist("demoer")

    prospect_blurb = ""
    if scenario:
        prospect_blurb = (
            f"Prospect: {scenario.get('client', 'unknown')}\n"
            f"Context: {scenario.get('description', '')}\n\n"
        )

    prompt = (
        f"{prospect_blurb}"
        "Drafted RFP answers:\n"
        f"{json.dumps(answers, indent=2)}\n\n"
        "Produce the presenter script per your output schema."
    )
    resp = client.messages.create(
        model=spec.model or "claude-opus-4-7",
        max_tokens=6144,  # Demoer output is large: client_pitch + 5 speaker-note sections
        system=spec.prompt,
        messages=[{"role": "user", "content": prompt}],
    )
    text = resp.content[0].text
    truncated = getattr(resp, "stop_reason", None) == "max_tokens"
    try:
        parsed = _extract_json(text)
        # Backfill the client_pitch shape if the model omitted it
        parsed.setdefault("client_pitch", {})
        cp = parsed["client_pitch"]
        cp.setdefault("headline", "")
        cp.setdefault("why_helios", "")
        cp.setdefault("value_pillars", [])
        cp.setdefault("tailored_to", "")
        return parsed
    except (json.JSONDecodeError, ValueError) as e:
        return {
            "raw_response": text,
            "parse_error": ("response_truncated" if truncated else str(e)),
            "client_pitch": {
                "headline": "",
                "why_helios": "",
                "value_pillars": [],
                "tailored_to": "",
            },
            "elevator_pitch": "",
            "top_talking_points": [],
            "key_differentiators": [],
            "likely_followups": [],
            "call_to_action": "",
        }


# ============================================================
# Parallel pipeline orchestration
# ============================================================

def run_pipeline_parallel(
    raw_text: str,
    api_key: str,
    on_event: Optional[Callable[[dict], None]] = None,
    rfp_name: str = "Interactive RFP Run",
    scenario: dict | None = None,
    parallelism: int = 4,
    use_specialists: bool = True,
    include_qa: bool = True,
    include_demo: bool = True,
) -> dict:
    """Run all five stages with PARALLEL question execution + reviewer + demoer.

    Stages:
      1. parse                  (sequential)
      2. retrieve_draft         (parallel — N workers)
      3. review (consistency)   (sequential, single LLM call)
      4. qa_review (reviewer)   (sequential, single LLM call) — optional
      5. demo (demoer)          (sequential, single LLM call) — optional
      6. export                 (sequential)
    """
    emit = on_event or (lambda _e: None)
    client = anthropic.Anthropic(api_key=api_key)

    # ---- Stage 1: parse ----
    emit({"type": "stage_start", "stage": "parse"})
    questions = parse_questionnaire(raw_text)
    emit({"type": "stage_done", "stage": "parse", "questions": questions})

    # ---- Stage 2: parallel retrieve+draft ----
    emit({"type": "stage_start", "stage": "retrieve_draft", "total": len(questions), "parallelism": parallelism})
    answers: list[dict] = [None] * len(questions)  # type: ignore

    # Each worker emits events through on_event; the main thread orchestrates.
    def _draft_one(idx: int, q: dict) -> dict:
        emit({"type": "question_start", "qid": q["id"], "text": q["text"], "category": q["category"]})
        # Each worker creates its own client to avoid contention
        worker_client = anthropic.Anthropic(api_key=api_key)
        ans = draft_answer(
            worker_client, q["id"], q["text"], q["category"],
            on_event=emit, use_specialists=use_specialists,
        )
        ans.setdefault("question_id", q["id"])
        ans.setdefault("category", q["category"])
        ans.setdefault("sources", [])
        ans.setdefault("confidence", "low")
        ans.setdefault("flags", [])
        emit({"type": "question_done", "qid": q["id"], "answer": ans})
        return idx, ans

    if parallelism > 1 and len(questions) > 1:
        with ThreadPoolExecutor(max_workers=parallelism) as pool:
            futures = [pool.submit(_draft_one, i, q) for i, q in enumerate(questions)]
            for fut in as_completed(futures):
                idx, ans = fut.result()
                answers[idx] = ans
    else:
        for i, q in enumerate(questions):
            _, answers[i] = _draft_one(i, q)

    emit({"type": "stage_done", "stage": "retrieve_draft", "answers_count": len(answers)})

    # ---- Stage 3: consistency review (existing) ----
    emit({"type": "stage_start", "stage": "review"})
    review = review_answers(client, answers)
    emit({"type": "stage_done", "stage": "review", "review": review})

    # ---- Stage 4: QA review (new — Senior Reviewer specialist) ----
    qa = None
    if include_qa:
        emit({"type": "stage_start", "stage": "qa_review"})
        qa = review_quality(client, answers)
        emit({"type": "stage_done", "stage": "qa_review", "qa_review": qa})

    # ---- Stage 5: Demo script (new — Sales Engineering Lead) ----
    demo = None
    if include_demo:
        emit({"type": "stage_start", "stage": "demo"})
        demo = generate_demo_script(client, answers, scenario=scenario)
        emit({"type": "stage_done", "stage": "demo", "demo_script": demo})

    # ---- Stage 6: export ----
    emit({"type": "stage_start", "stage": "export"})
    final = export(rfp_name, questions, answers, review,
                   model="claude-opus-4-7", qa_review=qa, demo_script=demo)
    emit({"type": "stage_done", "stage": "export", "final": final})
    emit({"type": "pipeline_complete", "final": final})
    return final


# ============================================================
# Pipeline orchestration with event streaming
# ============================================================

def run_pipeline(
    raw_text: str,
    api_key: str,
    on_event: Optional[Callable[[dict], None]] = None,
    rfp_name: str = "Interactive RFP Run",
) -> dict:
    """Run all five stages, emitting events for the UI as it goes."""
    emit = on_event or (lambda _e: None)
    client = anthropic.Anthropic(api_key=api_key)

    # Stage 1: parse
    emit({"type": "stage_start", "stage": "parse"})
    questions = parse_questionnaire(raw_text)
    emit({"type": "stage_done", "stage": "parse", "questions": questions})

    # Stages 2+3: retrieve+draft (interleaved per question)
    answers: list[dict] = []
    emit({"type": "stage_start", "stage": "retrieve_draft", "total": len(questions)})
    for q in questions:
        emit({"type": "question_start", "qid": q["id"], "text": q["text"], "category": q["category"]})
        ans = draft_answer(client, q["id"], q["text"], q["category"], on_event=on_event)
        # Defensive normalization
        ans.setdefault("question_id", q["id"])
        ans.setdefault("category", q["category"])
        ans.setdefault("sources", [])
        ans.setdefault("confidence", "low")
        ans.setdefault("flags", [])
        answers.append(ans)
        emit({"type": "question_done", "qid": q["id"], "answer": ans})
    emit({"type": "stage_done", "stage": "retrieve_draft"})

    # Stage 4: review
    emit({"type": "stage_start", "stage": "review"})
    review = review_answers(client, answers)
    emit({"type": "stage_done", "stage": "review", "review": review})

    # Stage 5: export
    emit({"type": "stage_start", "stage": "export"})
    final = export(rfp_name, questions, answers, review, model="claude-opus-4-7")
    emit({"type": "stage_done", "stage": "export", "final": final})

    emit({"type": "pipeline_complete", "final": final})
    return final
