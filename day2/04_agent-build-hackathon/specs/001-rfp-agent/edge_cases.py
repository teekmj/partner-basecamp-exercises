"""Edge case validator for the RFP agent.

Feeds three deliberately problematic questions through the agent and
verifies it handles each per spec (CHK601, CHK602, CHK603).
"""

import json
import os
import sys
import anthropic

API_KEY = os.environ.get("ANTHROPIC_API_KEY")
if not API_KEY:
    raise SystemExit(
        "ANTHROPIC_API_KEY is required. Set it in your environment, e.g.\n"
        "  export ANTHROPIC_API_KEY=<your-key-here>"
    )

client = anthropic.Anthropic(api_key=API_KEY)

# Mirror the KB / tool / agent loop from the notebook (kept minimal here)
KNOWLEDGE_BASE = {
    "threat_detection": {
        "source": "Helios Platform Architecture Doc v4.2",
        "content": "Helios Sentinel uses signature-based, behavioral, and ML detection. Latency: 2.3s signatures, 18s behavioral. SIEM 50K EPS.",
        "tags": ["technical", "detection", "latency"],
    },
    "compliance_certs": {
        "source": "Helios Compliance Register 2025",
        "content": "SOC 2 Type II Dec 2024, ISO 27001 Mar 2024, FedRAMP Moderate Jun 2024, PCI DSS Sep 2024.",
        "tags": ["compliance", "certifications"],
    },
    "pricing_model": {
        "source": "Helios Pricing Sheet Q1 2025",
        "content": "500 EP $18/seat/mo, 1000 EP $15/seat/mo, 5000 EP $11/seat/mo. Min 12 months.",
        "tags": ["pricing"],
    },
    "data_residency_eu": {
        "source": "Helios Data Sovereignty v3.1",
        "content": "EU residency in Frankfurt + Dublin. AES-256-GCM at rest, TLS 1.3 in transit.",
        "tags": ["technical", "compliance", "eu", "encryption"],
    },
}


def search_knowledge_base(query, category=None):
    query_terms = set(query.lower().split())
    results = []
    for entry_id, entry in KNOWLEDGE_BASE.items():
        text = (entry["content"] + " " + " ".join(entry["tags"])).lower()
        overlap = len(query_terms & set(text.split()))
        if category and category.lower() in [t.lower() for t in entry["tags"]]:
            overlap += 5
        if overlap > 0:
            results.append({"id": entry_id, "source": entry["source"], "content": entry["content"], "relevance_score": overlap})
    results.sort(key=lambda x: x["relevance_score"], reverse=True)
    return results[:3]


SEARCH_KB_TOOL = {
    "name": "search_kb",
    "description": "Search Helios KB for RFP-relevant information",
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {"type": "string"},
            "category": {"type": "string", "enum": ["technical", "compliance", "pricing", "company-info"]},
        },
        "required": ["query"],
    },
}


def handle_tool_call(name, inp):
    if name == "search_kb":
        return json.dumps(search_knowledge_base(inp["query"], inp.get("category")))
    return json.dumps({"error": "unknown tool"})


SYSTEM_PROMPT = """You are an RFP response agent for Helios Security.

For each question:
- Use search_kb if helpful
- If KB doesn't fully cover the question, set confidence to "low" or "medium" and add flags
- Be honest: don't fabricate data not in the KB

Return JSON: {"question_id": "...", "category": "...", "answer": "...", "sources": [...], "confidence": "high|medium|low", "flags": [...]}"""


def _extract_json(text):
    text = text.strip()
    if "```json" in text:
        text = text.split("```json", 1)[1].split("```", 1)[0]
    elif "```" in text:
        text = text.split("```", 1)[1].split("```", 1)[0]
    s, e = text.find("{"), text.rfind("}")
    if s != -1 and e > s:
        text = text[s : e + 1]
    return json.loads(text.strip())


def answer_single_question(qid, qtext, category):
    messages = [{"role": "user", "content": f"ID: {qid}, Category: {category}\nQuestion: {qtext}"}]
    for _ in range(5):
        resp = client.messages.create(
            model="claude-opus-4-7",
            max_tokens=2048,
            system=SYSTEM_PROMPT,
            messages=messages,
            tools=[SEARCH_KB_TOOL],
        )
        if resp.stop_reason == "end_turn":
            for block in resp.content:
                if block.type == "text":
                    try:
                        return _extract_json(block.text)
                    except Exception:
                        return {"raw_response": block.text, "parse_error": True}
            break
        if resp.stop_reason == "tool_use":
            messages.append({"role": "assistant", "content": resp.content})
            tool_results = []
            for block in resp.content:
                if block.type == "tool_use":
                    tool_results.append(
                        {"type": "tool_result", "tool_use_id": block.id, "content": handle_tool_call(block.name, block.input)}
                    )
            messages.append({"role": "user", "content": tool_results})
    return {"error": "max turns reached"}


# Edge case definitions
EDGE_CASES = [
    {
        "id": "E_OOS",
        "category": "technical",
        "text": "What is the airspeed velocity of an unladen swallow?",
        "check_id": "CHK601",
        "description": "Out-of-scope question handled (low confidence + flags)",
        "validate": lambda a: a.get("confidence") in ("low", "medium") and len(a.get("flags", [])) > 0,
    },
    {
        "id": "E_AMBIG",
        "category": "company-info",
        "text": "Tell us about your stuff.",
        "check_id": "CHK602",
        "description": "Ambiguous question handled gracefully",
        "validate": lambda a: bool(a.get("answer")) and a.get("confidence") in ("low", "medium") and len(a.get("flags", [])) > 0,
    },
    {
        "id": "E_TYPOS",
        "category": "pricing",
        "text": "Wat iz ur pricng for 500 endpointes?",
        "check_id": "CHK603",
        "description": "Question with typos still resolves to correct KB entry",
        "validate": lambda a: "$18" in a.get("answer", "") and a.get("confidence") in ("high", "medium"),
    },
]


def main():
    print("=" * 70)
    print("EDGE CASE VALIDATION")
    print("=" * 70)
    results = {}
    for ec in EDGE_CASES:
        print(f"\n[{ec['check_id']}] {ec['description']}")
        print(f"  Question: {ec['text']}")
        ans = answer_single_question(ec["id"], ec["text"], ec["category"])
        passed = ec["validate"](ans)
        results[ec["check_id"]] = {
            "description": ec["description"],
            "passed": passed,
            "confidence": ans.get("confidence"),
            "flags": ans.get("flags", []),
            "answer_preview": (ans.get("answer", "") or ans.get("raw_response", ""))[:200],
        }
        status = "✓" if passed else "✗"
        print(f"  {status} confidence={ans.get('confidence')} flags={len(ans.get('flags', []))}")
        print(f"     answer: {results[ec['check_id']]['answer_preview']}")

    # Update checklist.md and validation_report.json
    checklist_path = os.path.join(os.path.dirname(__file__), "checklist.md")
    report_path = os.path.join(os.path.dirname(__file__), "validation_report.json")

    if os.path.exists(checklist_path):
        with open(checklist_path) as f:
            text = f.read()
        for cid, r in results.items():
            marker = "[x]" if r["passed"] else "[✗]"
            import re
            text = re.sub(rf"- \[[ x✗]\] {cid} ", f"- {marker} {cid} ", text)
        with open(checklist_path, "w") as f:
            f.write(text)

    if os.path.exists(report_path):
        with open(report_path) as f:
            report = json.load(f)
        for cid, r in results.items():
            report["items"][cid] = {
                "description": r["description"],
                "passed": r["passed"],
                "detail": f"confidence={r['confidence']}, flags={len(r['flags'])}",
            }
        # Recompute aggregate
        total = len(report["items"])
        passed = sum(1 for v in report["items"].values() if v["passed"])
        report["total"] = total
        report["passed"] = passed
        report["failed"] = total - passed
        report["pass_rate"] = round(passed / total * 100, 1)
        with open(report_path, "w") as f:
            json.dump(report, f, indent=2)

    total = len(results)
    passed = sum(1 for r in results.values() if r["passed"])
    print(f"\n{'=' * 70}")
    print(f"EDGE CASES: {passed}/{total} passed")
    print("=" * 70)
    sys.exit(0 if passed == total else 1)


if __name__ == "__main__":
    main()
