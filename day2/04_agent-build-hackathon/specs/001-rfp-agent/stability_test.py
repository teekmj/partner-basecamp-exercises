"""Stability harness: run the agent N times, measure variance.

For each trial, captures:
  - review consistency_score
  - review issue count
  - eval pass rate
  - factual data point presence
  - per-run latency

Writes one JSON line per completed trial to results.jsonl so you can
tail the file while the harness runs. Aggregate stats are written to
stability_summary.json at the end.

Concurrency: a small thread pool (default 4) to stay under API rate
limits. Each trial does its own round of API calls.
"""

import argparse
import json
import os
import re
import sys
import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import anthropic

ROOT = Path(__file__).parent.parent.parent
RESULTS_PATH = Path(__file__).parent / "results.jsonl"
SUMMARY_PATH = Path(__file__).parent / "stability_summary.json"

API_KEY = os.environ.get("ANTHROPIC_API_KEY")
if not API_KEY:
    raise SystemExit(
        "ANTHROPIC_API_KEY is required. Set it in your environment, e.g.\n"
        "  export ANTHROPIC_API_KEY=<your-key-here>"
    )

# Each thread gets its own client to avoid contention
_thread_local = threading.local()


def get_client():
    if not hasattr(_thread_local, "client"):
        _thread_local.client = anthropic.Anthropic(api_key=API_KEY)
    return _thread_local.client


# ============================================================
# Embed agent code (mirrors notebook — kept here for isolation)
# ============================================================

KNOWLEDGE_BASE = {
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
            "Mid-tier endpoint counts price at the next-lower-tier rate (e.g., 850 → $18, 3,200 → $15). "
            "Min term 12 months. 2yr +5%, 3yr +10%. Full SIEM add-on +$6/seat/mo. MDR +$12/seat/mo."
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
            "EU residency: Frankfurt + Dublin. AES-256-GCM at rest (KMS or BYOK). "
            "TLS 1.3 in transit with cert pinning. GDPR DPA. NCC Group annual pentest. "
            "Retention 90d telemetry / 13mo alerts."
        ),
        "tags": ["technical", "compliance", "eu", "encryption"],
    },
}


def search_kb(query, category=None):
    qt = set(query.lower().split())
    res = []
    for eid, e in KNOWLEDGE_BASE.items():
        text = (e["content"] + " " + " ".join(e["tags"])).lower()
        score = len(qt & set(text.split()))
        if category and category.lower() in [t.lower() for t in e["tags"]]:
            score += 5
        if score > 0:
            res.append({"id": eid, "source": e["source"], "content": e["content"], "relevance_score": score})
    res.sort(key=lambda x: x["relevance_score"], reverse=True)
    return res[:3]


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


SYSTEM_PROMPT = """You are an AI assistant helping Helios Security respond to RFP questionnaires.

For each question:
1. Use search_kb to find relevant source material
2. Draft a polished, cited answer
3. Cite sources by name
4. Flag low-confidence answers
5. When the KB distinguishes a built-in capability from a paid add-on, preserve that distinction precisely
6. When citing pricing, explain non-standard endpoint counts if the KB describes a rule

Return JSON: {"question_id": "...", "category": "...", "answer": "...", "sources": [...], "confidence": "high|medium|low", "flags": [...]}"""


RFP = [
    {"id": "Q1", "category": "technical", "text": "Describe your platform's approach to real-time threat detection. What data sources are ingested, and what is the average detection-to-alert latency?"},
    {"id": "Q2", "category": "compliance", "text": "List all compliance certifications your organization currently holds (SOC 2, ISO 27001, FedRAMP, etc.) and the date of most recent audit for each."},
    {"id": "Q3", "category": "pricing", "text": "Provide per-seat pricing for 500, 1,000, and 5,000 endpoints. Are volume discounts available? Is there a minimum contract term?"},
    {"id": "Q4", "category": "company-info", "text": "How many customers do you currently serve in the financial services vertical? Provide 2–3 reference accounts."},
    {"id": "Q5", "category": "technical", "text": "How does your platform handle data residency requirements for customers operating in the EU? Describe encryption at rest and in transit."},
]


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


def answer_one(qid, qtext, category):
    client = get_client()
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
                        return {"raw_response": block.text, "parse_error": True, "question_id": qid, "category": category}
            break
        if resp.stop_reason == "tool_use":
            messages.append({"role": "assistant", "content": resp.content})
            tool_results = []
            for block in resp.content:
                if block.type == "tool_use":
                    if block.name == "search_kb":
                        result = json.dumps(search_kb(block.input["query"], block.input.get("category")))
                    else:
                        result = json.dumps({"error": "unknown tool"})
                    tool_results.append({"type": "tool_result", "tool_use_id": block.id, "content": result})
            messages.append({"role": "user", "content": tool_results})
    return {"error": "max turns", "question_id": qid, "category": category}


REVIEW_PROMPT_TMPL = """Review these RFP answers for cross-question consistency.

Answers:
{answers}

Flag an item ONLY if it is a genuine contradiction or factual error a prospect would catch.

1. CONTRADICTION = same fact stated differently across answers (e.g., "SOC 2 audited Dec 2024" vs "Nov 2024"). FLAG.
2. NOT a contradiction = same word at different scopes the answers explicitly distinguish (e.g., "built-in correlation engine" vs "full SIEM add-on" when both are acknowledged). DO NOT FLAG.
3. NOT a contradiction = topic mentioned in one answer but not another when out of the second's scope. DO NOT FLAG.
4. Tone differences only flag if extreme.

Return JSON: {{"issues": [], "consistency_score": "high|medium|low", "recommendations": []}}

If no genuine contradictions, set consistency_score to "high" and return empty issues. Limit to at most 5 items each."""


def review(answers):
    client = get_client()
    prompt = REVIEW_PROMPT_TMPL.format(answers=json.dumps(answers, indent=2))
    resp = client.messages.create(
        model="claude-opus-4-7",
        max_tokens=4096,
        messages=[{"role": "user", "content": prompt}],
    )
    text = resp.content[0].text
    try:
        return _extract_json(text)
    except Exception as e:
        return {"raw_response": text, "parse_error": str(e), "consistency_score": "unknown", "issues": [], "recommendations": []}


# ============================================================
# Per-trial measurement
# ============================================================

EXPECTED_FACTS = {
    "Q1": [["2.3 second", "2.3s"], ["18 second", "18s"]],
    "Q2": [["december 2024"]],
    "Q3": [["$18"], ["12 month"]],
    "Q4": [["47 customer"]],
    "Q5": [["aes-256-gcm"], ["tls 1.3"]],
}


def measure_facts(answers):
    by_id = {a.get("question_id"): a.get("answer", "").lower() for a in answers}
    total, hit = 0, 0
    miss = []
    for qid, groups in EXPECTED_FACTS.items():
        text = by_id.get(qid, "")
        for group in groups:
            total += 1
            if any(g.lower() in text for g in group):
                hit += 1
            else:
                miss.append(f"{qid}:{group[0]}")
    return hit, total, miss


def run_trial(trial_idx):
    t0 = time.time()
    try:
        answers = [answer_one(q["id"], q["text"], q["category"]) for q in RFP]
        rev = review(answers)
        elapsed = time.time() - t0

        # Validate per-trial structure
        all_have_sources = all(isinstance(a.get("sources"), list) and len(a["sources"]) >= 1 for a in answers)
        all_valid_conf = all(a.get("confidence") in {"high", "medium", "low"} for a in answers)
        review_parsed = isinstance(rev, dict) and "parse_error" not in rev

        fact_hit, fact_total, fact_miss = measure_facts(answers)

        return {
            "trial": trial_idx,
            "elapsed_s": round(elapsed, 1),
            "consistency_score": rev.get("consistency_score") if review_parsed else "parse_error",
            "issue_count": len(rev.get("issues", [])) if review_parsed else None,
            "review_parsed": review_parsed,
            "all_have_sources": all_have_sources,
            "all_valid_conf": all_valid_conf,
            "fact_rate": round(fact_hit / fact_total, 3) if fact_total else 0,
            "fact_misses": fact_miss,
            "issues": rev.get("issues", []) if review_parsed else [],
            "ok": all_have_sources and all_valid_conf and review_parsed,
        }
    except Exception as e:
        return {
            "trial": trial_idx,
            "elapsed_s": round(time.time() - t0, 1),
            "error": str(e)[:300],
            "ok": False,
        }


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--n", type=int, default=100, help="number of trials (default 100)")
    p.add_argument("--workers", type=int, default=4, help="parallel workers (default 4)")
    p.add_argument("--fresh", action="store_true", help="truncate results.jsonl before starting")
    args = p.parse_args()

    if args.fresh and RESULTS_PATH.exists():
        RESULTS_PATH.unlink()

    print(f"Running {args.n} trials with {args.workers} parallel workers")
    print(f"Streaming results to {RESULTS_PATH}")
    print(f"Final summary will write to {SUMMARY_PATH}")
    print()

    write_lock = threading.Lock()
    completed = 0
    t_start = time.time()

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = [pool.submit(run_trial, i) for i in range(args.n)]
        for fut in as_completed(futures):
            r = fut.result()
            with write_lock:
                completed += 1
                with open(RESULTS_PATH, "a") as f:
                    f.write(json.dumps(r) + "\n")
                # Print compact progress line
                if "error" in r:
                    print(f"[{completed:3}/{args.n}] trial {r['trial']:3} ERROR: {r['error'][:80]}", flush=True)
                else:
                    print(
                        f"[{completed:3}/{args.n}] trial {r['trial']:3} "
                        f"score={r['consistency_score']:6} issues={r['issue_count']} "
                        f"facts={r['fact_rate']:.0%} ok={r['ok']} ({r['elapsed_s']}s)",
                        flush=True,
                    )

    total_elapsed = time.time() - t_start
    print(f"\nAll {args.n} trials done in {total_elapsed/60:.1f} minutes")

    # Aggregate
    rows = []
    with open(RESULTS_PATH) as f:
        for line in f:
            rows.append(json.loads(line))

    n_total = len(rows)
    n_ok = sum(1 for r in rows if r.get("ok"))
    n_err = sum(1 for r in rows if "error" in r)
    score_dist = {}
    for r in rows:
        s = r.get("consistency_score", "missing")
        score_dist[s] = score_dist.get(s, 0) + 1
    issue_counts = [r.get("issue_count") for r in rows if r.get("issue_count") is not None]
    fact_rates = [r.get("fact_rate") for r in rows if r.get("fact_rate") is not None]
    elapsed_s = [r.get("elapsed_s") for r in rows if r.get("elapsed_s") is not None]
    sources_ok = sum(1 for r in rows if r.get("all_have_sources"))
    conf_ok = sum(1 for r in rows if r.get("all_valid_conf"))
    review_ok = sum(1 for r in rows if r.get("review_parsed"))

    pct = lambda n, d: round(n / d * 100, 1) if d else 0
    avg = lambda xs: round(sum(xs) / len(xs), 3) if xs else 0
    pctile = lambda xs, p: sorted(xs)[int(len(xs) * p)] if xs else 0

    summary = {
        "total_trials": n_total,
        "trials_with_no_errors": n_ok,
        "trials_pct_ok": pct(n_ok, n_total),
        "trials_with_exception": n_err,
        "consistency_score_distribution": score_dist,
        "consistency_high_pct": pct(score_dist.get("high", 0), n_total),
        "consistency_medium_pct": pct(score_dist.get("medium", 0), n_total),
        "consistency_low_pct": pct(score_dist.get("low", 0), n_total),
        "all_have_sources_pct": pct(sources_ok, n_total),
        "all_valid_confidence_pct": pct(conf_ok, n_total),
        "review_parseable_pct": pct(review_ok, n_total),
        "issue_count_avg": avg(issue_counts),
        "issue_count_zero_pct": pct(sum(1 for ic in issue_counts if ic == 0), len(issue_counts)),
        "fact_rate_avg": avg(fact_rates),
        "fact_rate_min": min(fact_rates) if fact_rates else 0,
        "fact_rate_p10": pctile(fact_rates, 0.1),
        "elapsed_avg_s": avg(elapsed_s),
        "elapsed_p50_s": pctile(elapsed_s, 0.5),
        "elapsed_p95_s": pctile(elapsed_s, 0.95),
        "elapsed_max_s": max(elapsed_s) if elapsed_s else 0,
        "wall_clock_minutes": round(total_elapsed / 60, 1),
    }

    with open(SUMMARY_PATH, "w") as f:
        json.dump(summary, f, indent=2)

    print()
    print("=" * 70)
    print("STABILITY SUMMARY")
    print("=" * 70)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
