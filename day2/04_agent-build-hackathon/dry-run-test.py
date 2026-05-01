#!/usr/bin/env python3
"""
Dry-run test for Agent Engineering Challenge Colab notebook.
Simulates the full participant experience end-to-end.

Runs: setup → KB + tools → Level 0 agent on Q1 → process_rfp (Part 5) →
      review_answers (Part 6) → export (Part 7) → eval assertions (Part 8)
"""

import os
import json
import time
import sys
from typing import Optional

# ============================================================
# TIMING INFRASTRUCTURE
# ============================================================
timings = {}

def timed(label):
    """Context manager to time a block and store the result."""
    class Timer:
        def __enter__(self):
            self.start = time.time()
            return self
        def __exit__(self, *args):
            elapsed = time.time() - self.start
            timings[label] = elapsed
            print(f"  [{label}] completed in {elapsed:.2f}s")
    return Timer()

# ============================================================
# STEP 1: Setup — install + init client + verify
# ============================================================
print("=" * 70)
print("STEP 1: Environment Setup")
print("=" * 70)

with timed("setup"):
    import anthropic

    ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")

    if not ANTHROPIC_API_KEY:
        print("FAIL: ANTHROPIC_API_KEY not found")
        sys.exit(1)

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    print("  Client initialized")

    # Verify API connectivity
    try:
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=20,
            messages=[{"role": "user", "content": "Say 'ready' and nothing else."}]
        )
        print(f"  API connection verified: {response.content[0].text}")
        print(f"  Model: {response.model}")
    except Exception as e:
        print(f"  FAIL: API connection failed: {e}")
        sys.exit(1)

print("  RESULT: PASS\n")


# ============================================================
# STEP 2: Mock KB setup and tool definition
# ============================================================
print("=" * 70)
print("STEP 2: Mock Knowledge Base & Tool Definition")
print("=" * 70)

with timed("kb_and_tools"):
    KNOWLEDGE_BASE = {
        "threat_detection": {
            "source": "Helios Platform Architecture Doc v4.2",
            "content": (
                "Helios Sentinel uses a multi-layered detection engine combining "
                "signature-based matching, behavioral analysis, and ML-driven anomaly detection. "
                "Data sources include endpoint telemetry (process events, file system changes, "
                "network connections), cloud workload logs (AWS CloudTrail, Azure Activity Log, "
                "GCP Audit Log), network flow data (NetFlow v9/IPFIX), and email gateway events. "
                "Average detection-to-alert latency is 2.3 seconds for signature matches and "
                "18 seconds for behavioral detections. Our SIEM correlation engine processes "
                "up to 50,000 events per second per tenant."
            ),
            "tags": ["technical", "detection", "latency", "architecture"]
        },
        "compliance_certs": {
            "source": "Helios Compliance & Certifications Register 2025",
            "content": (
                "Current certifications: SOC 2 Type II (audited December 2024 by Deloitte), "
                "ISO 27001:2022 (certified March 2024 by BSI), FedRAMP Moderate (authorized "
                "June 2024, sponsored by DHS), HIPAA (BAA available, last assessment October 2024), "
                "PCI DSS v4.0 Level 1 Service Provider (validated September 2024 by Coalfire). "
                "StateRAMP authorized (January 2025). All certifications maintained on continuous "
                "monitoring basis with quarterly internal audits."
            ),
            "tags": ["compliance", "certifications", "audit", "soc2", "fedramp"]
        },
        "pricing_model": {
            "source": "Helios Commercial Pricing Sheet Q1 2025",
            "content": (
                "Endpoint Protection Platform (EPP+EDR bundle): "
                "500 endpoints: $18/seat/month ($108,000/year). "
                "1,000 endpoints: $15/seat/month ($180,000/year) — 17% volume discount. "
                "5,000 endpoints: $11/seat/month ($660,000/year) — 39% volume discount. "
                "Minimum contract term: 12 months. Multi-year discounts: 2-year = additional 5%, "
                "3-year = additional 10%. SIEM add-on: +$6/seat/month. "
                "MDR add-on: +$12/seat/month. All pricing excludes professional services."
            ),
            "tags": ["pricing", "commercial", "discount", "contract"]
        },
        "financial_services_customers": {
            "source": "Helios Customer Success — Vertical Report 2024",
            "content": (
                "Helios currently serves 47 customers in financial services, including "
                "12 banks, 8 insurance carriers, 15 asset management firms, and 12 fintech companies. "
                "Reference accounts (approved for external use): "
                "1) Meridian National Bank — 3,200 endpoints, EPP+EDR+SIEM, deployed since 2022. "
                "2) Crestview Capital Partners — 850 endpoints, EPP+MDR, deployed since 2023. "
                "3) Apex Insurance Group — 5,100 endpoints, full platform, deployed since 2021. "
                "Average NPS in financial services vertical: 72."
            ),
            "tags": ["company-info", "customers", "financial-services", "references"]
        },
        "data_residency_eu": {
            "source": "Helios Data Sovereignty & Privacy Whitepaper v3.1",
            "content": (
                "Helios supports full EU data residency through dedicated infrastructure in "
                "Frankfurt (AWS eu-central-1) and Dublin (AWS eu-west-1). Customer data never "
                "leaves the selected region. Encryption at rest: AES-256-GCM with customer-managed "
                "keys (AWS KMS or BYOK). Encryption in transit: TLS 1.3 for all API and agent "
                "communications, with certificate pinning for endpoint agents. "
                "GDPR Data Processing Agreement (DPA) included in all EU contracts. "
                "Annual third-party penetration testing by NCC Group. "
                "Data retention: configurable per tenant, default 90 days for raw telemetry, "
                "13 months for aggregated alerts."
            ),
            "tags": ["technical", "compliance", "data-residency", "eu", "encryption", "gdpr"]
        },
        "past_rfp_detection_answer": {
            "source": "Acme Corp RFP Response — March 2024",
            "content": (
                "Q: Describe your real-time threat detection capabilities. "
                "A: Helios Sentinel provides sub-3-second detection for known threat patterns "
                "and under 20 seconds for behavioral anomalies. Our detection engine ingests "
                "endpoint telemetry, network flows, cloud audit logs, and email events. "
                "The SIEM correlation engine handles 50K EPS per tenant. "
                "We maintain a 99.7% true positive rate on our top 100 detection rules, "
                "validated quarterly against MITRE ATT&CK framework."
            ),
            "tags": ["technical", "detection", "past-rfp"]
        },
        "past_rfp_compliance_answer": {
            "source": "NovaTech RFP Response — July 2024",
            "content": (
                "Q: What compliance certifications do you hold? "
                "A: Helios holds SOC 2 Type II, ISO 27001, FedRAMP Moderate, PCI DSS v4.0, "
                "and HIPAA compliance. All certifications are actively maintained with "
                "continuous monitoring. We provide audit reports upon request under NDA. "
                "Our security team of 14 full-time engineers manages compliance programs."
            ),
            "tags": ["compliance", "certifications", "past-rfp"]
        }
    }

    def search_knowledge_base(query: str, category: Optional[str] = None) -> list[dict]:
        """Search the mock knowledge base."""
        query_terms = set(query.lower().split())
        results = []
        for entry_id, entry in KNOWLEDGE_BASE.items():
            entry_text = (entry["content"] + " " + " ".join(entry["tags"])).lower()
            overlap = len(query_terms & set(entry_text.split()))
            if category and category.lower() in [t.lower() for t in entry["tags"]]:
                overlap += 5
            if overlap > 0:
                results.append({
                    "id": entry_id,
                    "source": entry["source"],
                    "content": entry["content"],
                    "relevance_score": overlap
                })
        results.sort(key=lambda x: x["relevance_score"], reverse=True)
        return results[:3]

    # Quick test
    test_results = search_knowledge_base("threat detection latency", category="technical")
    print(f"  Knowledge base loaded ({len(KNOWLEDGE_BASE)} entries)")
    print(f"  Test search 'threat detection latency': {len(test_results)} results")
    print(f"  Top result: {test_results[0]['source']}")

    # Tool definition
    SEARCH_KB_TOOL = {
        "name": "search_kb",
        "description": (
            "Search the Helios Security knowledge base for information relevant to "
            "answering an RFP question. Returns up to 3 matching documents with source "
            "attribution. Use this to find product docs, past proposal answers, compliance "
            "records, and pricing information."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query — use keywords from the RFP question"
                },
                "category": {
                    "type": "string",
                    "enum": ["technical", "compliance", "pricing", "company-info"],
                    "description": "Optional category filter to narrow results"
                }
            },
            "required": ["query"]
        }
    }

    def handle_tool_call(tool_name: str, tool_input: dict) -> str:
        """Execute a tool call and return the result as a string."""
        if tool_name == "search_kb":
            results = search_knowledge_base(
                query=tool_input["query"],
                category=tool_input.get("category")
            )
            return json.dumps(results, indent=2)
        else:
            return json.dumps({"error": f"Unknown tool: {tool_name}"})

    print("  Tool definition ready")

print("  RESULT: PASS\n")


# ============================================================
# STEP 3: Level 0 Agent — System prompt + answer_single_question + Q1 test
# ============================================================
print("=" * 70)
print("STEP 3: Level 0 Agent — answer Q1")
print("=" * 70)

SYSTEM_PROMPT = """You are an AI assistant helping Helios Security respond to RFP questionnaires.

For each question, you must:
1. Use the search_kb tool to find relevant source material
2. Draft a professional, detailed answer grounded in the retrieved sources
3. Cite your sources by name
4. If the knowledge base doesn't contain enough information, flag the answer as low-confidence

Return your answer as JSON with this structure:
{
    "question_id": "Q1",
    "category": "technical",
    "answer": "Your drafted answer here...",
    "sources": ["Source Name 1", "Source Name 2"],
    "confidence": "high" | "medium" | "low",
    "flags": ["any concerns or notes for human review"]
}

Be specific, professional, and concise. Use concrete numbers from the source material."""


def answer_single_question(
    question_id: str,
    question_text: str,
    category: str,
    model: str = "claude-sonnet-4-20250514",
) -> dict:
    """Level 0 agent: answers a single RFP question with tool use."""
    messages = [
        {
            "role": "user",
            "content": (
                f"Answer this RFP question.\n\n"
                f"Question ID: {question_id}\n"
                f"Category: {category}\n"
                f"Question: {question_text}\n\n"
                f"Search the knowledge base for relevant information, then draft your answer."
            )
        }
    ]

    max_turns = 5
    tool_calls_made = 0
    for turn in range(max_turns):
        response = client.messages.create(
            model=model,
            max_tokens=2048,
            system=SYSTEM_PROMPT,
            messages=messages,
            tools=[SEARCH_KB_TOOL],
        )

        if response.stop_reason == "end_turn":
            for block in response.content:
                if block.type == "text":
                    try:
                        text = block.text
                        if "```json" in text:
                            text = text.split("```json")[1].split("```")[0]
                        elif "```" in text:
                            text = text.split("```")[1].split("```")[0]
                        result = json.loads(text.strip())
                        result["_meta"] = {"tool_calls": tool_calls_made, "turns": turn + 1}
                        return result
                    except json.JSONDecodeError:
                        return {"raw_response": block.text, "parse_error": True}
            break

        if response.stop_reason == "tool_use":
            messages.append({"role": "assistant", "content": response.content})
            tool_results = []
            for block in response.content:
                if block.type == "tool_use":
                    tool_calls_made += 1
                    print(f"    Tool call #{tool_calls_made}: search_kb(query='{block.input.get('query','')[:50]}...', category={block.input.get('category')})")
                    result = handle_tool_call(block.name, block.input)
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": result,
                    })
            messages.append({"role": "user", "content": tool_results})

    return {"error": "Max turns reached without completing"}


with timed("level0_q1"):
    print("  Answering Q1 (threat detection)...")
    q1_result = answer_single_question(
        question_id="Q1",
        question_text=(
            "Describe your platform's approach to real-time threat detection. "
            "What data sources are ingested, and what is the average detection-to-alert latency?"
        ),
        category="technical",
    )

# Analyze Q1 result
print("\n  --- Q1 Result ---")
print(json.dumps(q1_result, indent=2))

q1_ok = (
    not q1_result.get("parse_error")
    and not q1_result.get("error")
    and "answer" in q1_result
    and len(q1_result.get("sources", [])) > 0
)
print(f"\n  RESULT: {'PASS' if q1_ok else 'FAIL'}")
if q1_ok:
    print(f"  Sources cited: {q1_result.get('sources', [])}")
    print(f"  Confidence: {q1_result.get('confidence')}")
    print(f"  Tool calls made: {q1_result.get('_meta', {}).get('tool_calls', '?')}")
print()


# ============================================================
# STEP 4: Part 5 — process_rfp() (participant implementation)
# ============================================================
print("=" * 70)
print("STEP 4: Part 5 — Multi-Question Agent (process_rfp)")
print("=" * 70)

RFP_QUESTIONS = [
    {
        "id": "Q1",
        "category": "technical",
        "text": (
            "Describe your platform's approach to real-time threat detection. "
            "What data sources are ingested, and what is the average detection-to-alert latency?"
        ),
    },
    {
        "id": "Q2",
        "category": "compliance",
        "text": (
            "List all compliance certifications your organization currently holds "
            "(SOC 2, ISO 27001, FedRAMP, etc.) and the date of most recent audit for each."
        ),
    },
    {
        "id": "Q3",
        "category": "pricing",
        "text": (
            "Provide per-seat pricing for 500, 1,000, and 5,000 endpoints. "
            "Are volume discounts available? Is there a minimum contract term?"
        ),
    },
    {
        "id": "Q4",
        "category": "company-info",
        "text": (
            "How many customers do you currently serve in the financial services vertical? "
            "Provide 2-3 reference accounts."
        ),
    },
    {
        "id": "Q5",
        "category": "technical",
        "text": (
            "How does your platform handle data residency requirements for customers "
            "operating in the EU? Describe encryption at rest and in transit."
        ),
    },
]

# ---- PARTICIPANT IMPLEMENTATION: Simple sequential approach ----
def process_rfp(questions: list[dict]) -> list[dict]:
    """Process a full RFP questionnaire and return structured answers."""
    answers = []
    for i, q in enumerate(questions):
        print(f"\n  Processing {q['id']} ({q['category']})...")
        q_start = time.time()
        result = answer_single_question(
            question_id=q["id"],
            question_text=q["text"],
            category=q["category"],
        )
        q_elapsed = time.time() - q_start
        print(f"    Done in {q_elapsed:.2f}s | confidence={result.get('confidence','?')} | sources={len(result.get('sources',[]))}")
        answers.append(result)
    return answers

with timed("process_rfp_all"):
    all_answers = process_rfp(RFP_QUESTIONS)

# Summarize
print(f"\n  --- Summary ---")
rfp_ok = len(all_answers) == len(RFP_QUESTIONS) and all("answer" in a for a in all_answers)
for ans in all_answers:
    q_id = ans.get('question_id', '?')
    conf = ans.get('confidence', '?')
    src_count = len(ans.get('sources', []))
    answer_len = len(ans.get('answer', ''))
    flags = ans.get('flags', [])
    print(f"  {q_id}: confidence={conf}, sources={src_count}, answer_len={answer_len}, flags={flags}")

print(f"\n  RESULT: {'PASS' if rfp_ok else 'FAIL'} ({len(all_answers)}/{len(RFP_QUESTIONS)} answered)")
print()


# ============================================================
# STEP 5: Part 6 — review_answers() (participant implementation)
# ============================================================
print("=" * 70)
print("STEP 5: Part 6 — Consistency Review")
print("=" * 70)

def review_answers(answers: list[dict]) -> dict:
    """Review all drafted answers for cross-question consistency."""
    # Format all answers into a single prompt
    answers_text = ""
    for ans in answers:
        answers_text += f"\n--- {ans.get('question_id', '?')} ({ans.get('category', '?')}) ---\n"
        answers_text += f"Answer: {ans.get('answer', 'N/A')}\n"
        answers_text += f"Sources: {', '.join(ans.get('sources', []))}\n"
        answers_text += f"Confidence: {ans.get('confidence', '?')}\n"

    review_prompt = f"""You are reviewing a set of RFP answers drafted by an AI agent for Helios Security. 
Your job is to check for cross-answer consistency.

Look for:
1. **Contradictions**: Do any answers state conflicting facts (dates, numbers, capabilities)?
2. **Inconsistent data points**: Are the same metrics quoted differently across answers?
3. **Tone mismatches**: Is the tone consistent across all answers?
4. **Missing cross-references**: Where answers touch related topics, do they align?

Here are all the drafted answers:
{answers_text}

Return your review as JSON:
{{
    "status": "pass" | "issues_found",
    "issues": [
        {{
            "type": "contradiction" | "inconsistency" | "tone_mismatch" | "missing_info",
            "questions_involved": ["Q1", "Q3"],
            "description": "Describe the issue",
            "suggested_fix": "How to resolve it"
        }}
    ],
    "overall_assessment": "Brief summary of answer quality and consistency"
}}"""

    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=2048,
        messages=[{"role": "user", "content": review_prompt}]
    )

    for block in response.content:
        if block.type == "text":
            try:
                text = block.text
                if "```json" in text:
                    text = text.split("```json")[1].split("```")[0]
                elif "```" in text:
                    text = text.split("```")[1].split("```")[0]
                return json.loads(text.strip())
            except json.JSONDecodeError:
                return {"raw_response": block.text, "parse_error": True}

    return {"error": "No text response from review"}


with timed("review_answers"):
    if all_answers:
        print("  Running consistency review...")
        review = review_answers(all_answers)
    else:
        review = {"error": "No answers to review"}

print("\n  --- Review Result ---")
print(json.dumps(review, indent=2))
review_ok = not review.get("parse_error") and not review.get("error")
print(f"\n  RESULT: {'PASS' if review_ok else 'FAIL'}")
if review_ok:
    issue_count = len(review.get("issues", []))
    print(f"  Status: {review.get('status', '?')}")
    print(f"  Issues found: {issue_count}")
    for issue in review.get("issues", []):
        print(f"    - [{issue.get('type')}] {issue.get('questions_involved', [])}: {issue.get('description', '')[:100]}")
print()


# ============================================================
# STEP 6: Part 7 — Export
# ============================================================
print("=" * 70)
print("STEP 6: Part 7 — Export Final Output")
print("=" * 70)

with timed("export"):
    final_output = {
        "rfp_name": "Sample RFP — Agent Engineering Challenge",
        "total_questions": len(RFP_QUESTIONS),
        "answers": all_answers if all_answers else [],
        "review": review if review else "Review not completed",
        "metadata": {
            "model": "claude-sonnet-4-20250514",
            "knowledge_base_entries": len(KNOWLEDGE_BASE),
        }
    }
    export_json = json.dumps(final_output, indent=2)
    print(f"  Export JSON length: {len(export_json)} chars")
    print(f"  Total questions: {final_output['total_questions']}")
    print(f"  Answers included: {len(final_output['answers'])}")

export_ok = len(final_output["answers"]) == len(RFP_QUESTIONS)
print(f"\n  RESULT: {'PASS' if export_ok else 'FAIL'}")
print()


# ============================================================
# STEP 7: Part 8 — Eval Assertions
# ============================================================
print("=" * 70)
print("STEP 7: Part 8 — Eval Assertions")
print("=" * 70)

with timed("evals"):
    def run_evals(answers: list[dict]) -> dict:
        """Run quality assertions against agent output."""
        results = {"passed": 0, "failed": 0, "details": []}

        for ans in answers:
            # Assertion 1: every answer has sources
            has_sources = len(ans.get("sources", [])) > 0
            results["details"].append({
                "question": ans.get("question_id"),
                "assertion": "has_sources",
                "passed": has_sources,
            })
            if has_sources:
                results["passed"] += 1
            else:
                results["failed"] += 1

            # Assertion 2: confidence is a valid value
            valid_confidence = ans.get("confidence") in ("high", "medium", "low")
            results["details"].append({
                "question": ans.get("question_id"),
                "assertion": "valid_confidence",
                "passed": valid_confidence,
            })
            if valid_confidence:
                results["passed"] += 1
            else:
                results["failed"] += 1

            # Assertion 3: answer is non-empty and reasonably long
            answer_text = ans.get("answer", "")
            has_substance = len(answer_text) > 50
            results["details"].append({
                "question": ans.get("question_id"),
                "assertion": "answer_has_substance (>50 chars)",
                "passed": has_substance,
            })
            if has_substance:
                results["passed"] += 1
            else:
                results["failed"] += 1

            # Assertion 4: no parse errors
            no_parse_error = not ans.get("parse_error", False)
            results["details"].append({
                "question": ans.get("question_id"),
                "assertion": "no_parse_error",
                "passed": no_parse_error,
            })
            if no_parse_error:
                results["passed"] += 1
            else:
                results["failed"] += 1

        # Assertion 5: Q3 (pricing) answer contains dollar amounts
        q3 = next((a for a in answers if a.get("question_id") == "Q3"), None)
        if q3:
            has_pricing = "$" in q3.get("answer", "")
            results["details"].append({
                "question": "Q3",
                "assertion": "pricing_answer_contains_dollar_amounts",
                "passed": has_pricing,
            })
            if has_pricing:
                results["passed"] += 1
            else:
                results["failed"] += 1

        # Assertion 6: Q2 (compliance) mentions specific certs
        q2 = next((a for a in answers if a.get("question_id") == "Q2"), None)
        if q2:
            answer_lower = q2.get("answer", "").lower()
            has_certs = "soc 2" in answer_lower and "fedramp" in answer_lower
            results["details"].append({
                "question": "Q2",
                "assertion": "compliance_answer_mentions_soc2_and_fedramp",
                "passed": has_certs,
            })
            if has_certs:
                results["passed"] += 1
            else:
                results["failed"] += 1

        # Assertion 7: All 5 question IDs present
        q_ids = {a.get("question_id") for a in answers}
        all_present = q_ids == {"Q1", "Q2", "Q3", "Q4", "Q5"}
        results["details"].append({
            "question": "ALL",
            "assertion": "all_question_ids_present",
            "passed": all_present,
        })
        if all_present:
            results["passed"] += 1
        else:
            results["failed"] += 1

        return results


    if all_answers:
        eval_results = run_evals(all_answers)
        print(f"  Eval Results: {eval_results['passed']} passed, {eval_results['failed']} failed")
        for detail in eval_results["details"]:
            status = "PASS" if detail["passed"] else "FAIL"
            print(f"    [{status}] {detail['question']}: {detail['assertion']}")
    else:
        eval_results = {"passed": 0, "failed": 0, "details": []}
        print("  No answers to evaluate")

evals_ok = eval_results["failed"] == 0
print(f"\n  RESULT: {'PASS' if evals_ok else 'PARTIAL — some assertions failed'}")
print()


# ============================================================
# FINAL REPORT
# ============================================================
print("=" * 70)
print("FINAL REPORT")
print("=" * 70)

total_time = sum(timings.values())

print("\n  TIMING BREAKDOWN:")
print(f"  {'Step':<30} {'Time':>10}")
print(f"  {'-'*30} {'-'*10}")
for label, t in timings.items():
    print(f"  {label:<30} {t:>8.2f}s")
print(f"  {'-'*30} {'-'*10}")
print(f"  {'TOTAL':<30} {total_time:>8.2f}s")

print("\n  STEP RESULTS:")
steps = [
    ("Step 1: Setup", True),
    ("Step 2: KB & Tools", True),
    ("Step 3: Level 0 Agent (Q1)", q1_ok),
    ("Step 4: process_rfp (Part 5)", rfp_ok),
    ("Step 5: review_answers (Part 6)", review_ok),
    ("Step 6: Export (Part 7)", export_ok),
    ("Step 7: Evals (Part 8)", evals_ok),
]
for name, ok in steps:
    print(f"    {'PASS' if ok else 'FAIL'} — {name}")

print("\n  ANSWER QUALITY ANALYSIS:")
if all_answers:
    for ans in all_answers:
        q_id = ans.get("question_id", "?")
        answer_text = ans.get("answer", "")
        sources = ans.get("sources", [])
        confidence = ans.get("confidence", "?")
        flags = ans.get("flags", [])

        # Check grounding
        grounded = any(
            src.lower() in answer_text.lower()
            for src in sources
        ) if sources else False

        # Check for specific numbers/data
        has_numbers = any(char.isdigit() for char in answer_text)

        print(f"\n  {q_id}:")
        print(f"    Answer length: {len(answer_text)} chars")
        print(f"    Sources: {sources}")
        print(f"    Confidence: {confidence}")
        print(f"    Cites sources in text: {grounded}")
        print(f"    Contains specific data: {has_numbers}")
        print(f"    Flags: {flags}")
        print(f"    First 200 chars: {answer_text[:200]}...")

print("\n  REVIEW ANALYSIS:")
if review and not review.get("error"):
    print(f"    Status: {review.get('status', '?')}")
    print(f"    Issues found: {len(review.get('issues', []))}")
    print(f"    Overall: {review.get('overall_assessment', 'N/A')}")
    for issue in review.get("issues", []):
        print(f"    - [{issue.get('type')}] {issue.get('description', '')}")

print("\n  PARTICIPANT EXPERIENCE ASSESSMENT:")
print(f"    Total API time: {total_time:.1f}s")
print(f"    Estimated coding time (Parts 5+6+8): ~15-25 min for simple approach")
print(f"    Estimated total time with reading + coding + debugging: ~40-55 min")
print(f"    Buffer for demo prep: {65 - 55:.0f}-{65 - 40:.0f} min")
print(f"    Verdict: {'Doable in 65 min' if total_time < 300 else 'Tight — API latency may be a factor'}")

all_passed = all(ok for _, ok in steps)
print(f"\n  OVERALL: {'ALL STEPS PASSED' if all_passed else 'SOME STEPS FAILED'}")
print("=" * 70)
