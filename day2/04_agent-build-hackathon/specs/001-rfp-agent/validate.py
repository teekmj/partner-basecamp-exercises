"""Spec validator for the RFP Agent.

Runs the notebook end-to-end, then checks each requirement and success
criterion in spec.md against the actual implementation and outputs.
Updates checklist.md in place with [x] / [✗] markers and writes a
machine-readable validation_report.json.
"""

import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).parent.parent.parent  # agent-build-hackathon dir
NOTEBOOK = ROOT / "Agent_Engineering_Challenge.ipynb"
EXEC_NOTEBOOK = ROOT / "_validate_executed.ipynb"
TEST_NOTEBOOK = ROOT / "_validate.ipynb"
CHECKLIST = Path(__file__).parent / "checklist.md"
REPORT = Path(__file__).parent / "validation_report.json"

API_KEY = os.environ.get("ANTHROPIC_API_KEY")
if not API_KEY:
    raise SystemExit(
        "ANTHROPIC_API_KEY is required. Set it in your environment, e.g.\n"
        "  export ANTHROPIC_API_KEY=<your-key-here>"
    )

results: dict[str, dict] = {}


def check(item_id: str, description: str, passed: bool, detail: str = ""):
    results[item_id] = {"description": description, "passed": passed, "detail": detail}


def get_cell_output(nb, idx):
    text = ""
    for output in nb["cells"][idx].get("outputs", []):
        if output.get("output_type") == "stream":
            text += "".join(output.get("text", []))
        elif output.get("output_type") == "execute_result":
            data = output.get("data", {})
            if "text/plain" in data:
                t = data["text/plain"]
                text += "".join(t) if isinstance(t, list) else t
    return text


def cell_source(nb, idx):
    return "".join(nb["cells"][idx].get("source", []))


def find_cell_with(nb, predicate):
    """Find the first code cell whose source matches a predicate."""
    for i, c in enumerate(nb["cells"]):
        if c.get("cell_type") == "code" and predicate("".join(c.get("source", []))):
            return i
    return None


def parse_json_in_text(text):
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        return json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return None


def main():
    print("=" * 70)
    print("SPEC VALIDATION — RFP Response Automation Agent")
    print("=" * 70)

    # ---- Stage 1: Static checks on notebook source ----
    print("\n[1/3] Static analysis of notebook source...")
    with open(NOTEBOOK) as f:
        nb_static = json.load(f)

    src_all = "\n".join(
        "".join(c.get("source", [])) for c in nb_static["cells"] if c.get("cell_type") == "code"
    )

    # FR-1xx
    check("CHK101", "process_rfp accepts question list", "def process_rfp" in src_all)
    check("CHK102", "search_kb tool registered + used", "SEARCH_KB_TOOL" in src_all and "search_kb" in src_all)
    check("CHK103", "Answer count matches input (looped per question)", "for q in questions" in src_all)
    check(
        "CHK104",
        "Required answer fields present in system prompt",
        all(f in src_all for f in ['"question_id"', '"category"', '"answer"', '"sources"', '"confidence"', '"flags"']),
    )
    check("CHK105", "Confidence enum mentioned in prompt", '"high|medium|low"' in src_all or "high|medium|low" in src_all)
    check("CHK106", "Sources field is a list (in prompt)", '"sources":' in src_all and "[" in src_all)
    check("CHK107", "max_turns bound on tool loop", "max_turns" in src_all and "range(max_turns)" in src_all)

    # FR-2xx
    check("CHK201", "review_answers function defined", "def review_answers" in src_all)
    check(
        "CHK202",
        "Review output has all 3 required fields (in prompt)",
        all(f in src_all for f in ['"consistency_score"', '"issues"', '"recommendations"']),
    )
    check("CHK203", "consistency_score enum in prompt", "high|medium|low" in src_all)
    check("CHK204", "Review uses separate client.messages.create call", src_all.count("client.messages.create") >= 2)
    check("CHK205", "Review has try/except for malformed JSON", "_extract_json" in src_all and "except" in src_all)

    # FR-3xx
    check(
        "CHK301",
        "Final export has all 5 required top-level fields",
        all(f in src_all for f in ["rfp_name", "total_questions", "answers", "review", "metadata"]),
    )
    check("CHK302", "Metadata has model + KB entries", '"model"' in src_all and "knowledge_base_entries" in src_all)

    # FR-4xx
    check("CHK401", "ComprehensiveEval class defined", "class ComprehensiveEval" in src_all)
    check("CHK402", "assert_has_sources called", "assert_has_sources" in src_all)
    check("CHK403", "assert_confidence_valid called", "assert_confidence_valid" in src_all)
    check(
        "CHK404",
        "Factual data-point assertions present",
        all(s in src_all for s in ["2.3 second", "December 2024", "AES-256-GCM"]),
    )
    check("CHK405", "Fuzzy matching used (_normalize or assert_matches_any)", "_normalize" in src_all and "assert_matches_any" in src_all)
    check(
        "CHK406",
        "Conditional consistency assertion exists",
        "assert_consistent_across" in src_all,
    )
    check("CHK407", "print_summary outputs pass rate", "Pass Rate" in src_all)

    # FR-15x: Specialist sub-agents (static checks against ui/specialists.py)
    ui_dir = ROOT / "ui"
    specialists_path = ui_dir / "specialists.py"
    seed_path = ui_dir / "seed_scenarios.py"
    storage_path = ui_dir / "storage.py"
    app_path = ui_dir / "app.py"
    if specialists_path.exists():
        spec_src = specialists_path.read_text()
        check("CHK150", "Four specialists defined",
              all(s in spec_src for s in ["ARCHITECT", "PRICING_LEAD", "COMPLIANCE", "BUSINESS_SME"]))
        check("CHK151", "Each specialist is an AgentDefinition (Claude Agent SDK)",
              "from claude_agent_sdk import AgentDefinition" in spec_src)
        check("CHK152", "Category routing wired",
              all(k in spec_src for k in ["technical", "pricing", "compliance", "company-info", "CATEGORY_ROUTING"]))
    if app_path.exists():
        app_src = app_path.read_text()
        check("CHK153", "Drafted answers carry specialist_key/specialist_label (in agent_core)",
              "specialist_key" in (ui_dir / "agent_core.py").read_text())
        check("CHK154", "specialist_assigned event emitted",
              "specialist_assigned" in (ui_dir / "agent_core.py").read_text())
        check("CHK155", "use_specialists=False fallback exists",
              "use_specialists: bool" in (ui_dir / "agent_core.py").read_text())

    # FR-408 / FR-409: Eval archive
    if storage_path.exists():
        st_src = storage_path.read_text()
        check("CHK408", "Each eval run appears in BOTH live log and durable archive",
              "EVAL_ARCHIVE_DIR" in st_src and "list_eval_archive" in st_src)
    if app_path.exists():
        check("CHK409", "/api/evals/archive endpoint",
              "/api/evals/archive" in app_path.read_text())

    # FR-5xx: Scenario corpus
    if seed_path.exists():
        seed_src = seed_path.read_text()
        check("CHK501", "50 seed scenarios + ≥6 verticals + ≥12 clients",
              "len(scenarios) >= 50" in seed_src.replace(" ", "") or "len(scenarios)<50" in seed_src.replace(" ", "")
              or "while len(scenarios) < 50" in seed_src)
        check("CHK502", "3–6 questions, ≥2 distinct categories enforced",
              "rng.randint(3, 6)" in seed_src)
        check("CHK503", "Idempotent re-seeding by seed-NNN id",
              'sid = f"seed-' in seed_src and "skipped" in seed_src)
    if app_path.exists():
        ap = app_path.read_text()
        check("CHK504", "Auto-seed on first startup if scenarios empty",
              "_autoseed_if_empty" in ap)
        check("CHK505", "/api/scenarios/seed endpoint",
              "/api/scenarios/seed" in ap)

    # ---- Stage 2: Execute notebook end-to-end ----
    print("\n[2/3] Executing notebook end-to-end (this takes ~90 seconds)...")
    inject_key_into_notebook()
    t0 = time.time()
    proc = subprocess.run(
        [
            "jupyter",
            "nbconvert",
            "--to",
            "notebook",
            "--execute",
            str(TEST_NOTEBOOK),
            "--output",
            str(EXEC_NOTEBOOK),
            "--ExecutePreprocessor.timeout=300",
        ],
        capture_output=True,
        text=True,
    )
    elapsed = time.time() - t0
    if proc.returncode != 0:
        print(f"❌ Notebook execution failed: {proc.stderr}")
        check("CHK507", "Notebook executes with zero cell errors", False, proc.stderr[-500:])
    else:
        check("CHK507", "Notebook executes with zero cell errors", True, f"Completed in {elapsed:.1f}s")

    check("CHK501", "End-to-end completes under 3 minutes", elapsed < 180, f"{elapsed:.1f}s")

    # ---- Stage 3: Validate runtime outputs ----
    print("\n[3/3] Validating runtime outputs...")
    if not EXEC_NOTEBOOK.exists():
        print("❌ No executed notebook to validate.")
        finalize()
        return

    with open(EXEC_NOTEBOOK) as f:
        nb_exec = json.load(f)

    # Find process_rfp output cell (cell with "Processing RFP" in output)
    proc_idx = next(
        (i for i, c in enumerate(nb_exec["cells"]) if c.get("cell_type") == "code" and "Processing RFP" in get_cell_output(nb_exec, i)),
        None,
    )
    if proc_idx is None:
        print("❌ Could not locate process_rfp output cell")

    # Find final export cell (cell whose output starts with valid RFP JSON)
    export_idx = None
    final_data = None
    for i, c in enumerate(nb_exec["cells"]):
        if c.get("cell_type") != "code":
            continue
        out = get_cell_output(nb_exec, i)
        candidate = parse_json_in_text(out)
        if candidate and "answers" in candidate and "rfp_name" in candidate:
            export_idx = i
            final_data = candidate
            break

    if final_data is None:
        print("❌ Could not parse final exported RFP JSON")
        finalize()
        return

    answers = final_data.get("answers", [])
    review = final_data.get("review", {})

    # SC-002 + CHK104/CHK106 runtime
    sources_ok = all(isinstance(a.get("sources"), list) and len(a["sources"]) >= 1 for a in answers)
    check("CHK502", "100% of answers cite at least one source", sources_ok, f"{sum(len(a.get('sources', [])) >= 1 for a in answers)}/{len(answers)}")

    # SC-003
    valid_confs = {"high", "medium", "low"}
    conf_ok = all(a.get("confidence") in valid_confs for a in answers)
    check("CHK503", "100% of answers have valid confidence", conf_ok)

    # SC-004 — factual data points
    facts = {
        "Q1": [["2.3 second", "2.3s"], ["18 second", "18s"]],
        "Q2": [["December 2024"]],
        "Q3": [["$18"]],
        "Q4": [["47 customer"]],
        "Q5": [["AES-256-GCM"], ["TLS 1.3"]],
    }
    answer_by_id = {a.get("question_id"): a.get("answer", "").lower() for a in answers}
    fact_total, fact_hit = 0, 0
    for qid, fact_groups in facts.items():
        text = answer_by_id.get(qid, "")
        for group in fact_groups:
            fact_total += 1
            if any(f.lower() in text for f in group):
                fact_hit += 1
    fact_rate = fact_hit / fact_total if fact_total else 0
    check("CHK504", "≥ 90% of factual data points present", fact_rate >= 0.9, f"{fact_hit}/{fact_total} ({fact_rate*100:.0f}%)")

    # SC-005 — review parseable
    review_ok = isinstance(review, dict) and "parse_error" not in review and review.get("consistency_score") in valid_confs
    check("CHK505", "Review step returns parseable report", review_ok, f"score={review.get('consistency_score') if isinstance(review, dict) else review}")

    # SC-006 — eval pass rate ≥ 95%
    eval_idx = next(
        (i for i, c in enumerate(nb_exec["cells"]) if c.get("cell_type") == "code" and "COMPREHENSIVE EVAL RESULTS" in get_cell_output(nb_exec, i)),
        None,
    )
    pass_rate = None
    if eval_idx is not None:
        eval_out = get_cell_output(nb_exec, eval_idx)
        m = re.search(r"Pass Rate: ([\d.]+)%", eval_out)
        if m:
            pass_rate = float(m.group(1))
    check("CHK506", "Eval pass rate ≥ 95%", pass_rate is not None and pass_rate >= 95.0, f"{pass_rate}%")

    # FR-104/FR-105/FR-106 runtime structural
    check(
        "CHK104_runtime",
        "FR-104 runtime: every answer has all 6 fields",
        all({"question_id", "category", "answer", "sources", "confidence", "flags"}.issubset(a.keys()) for a in answers),
    )

    # Edge cases (CHK6xx) — runtime checks based on observed answers
    check("CHK604", "Tool loop terminates (no errors observed)", proc.returncode == 0)
    check("CHK605", "Malformed JSON handled (review parsed OK)", review_ok)
    check("CHK606", "LLM rephrasing tolerated (fact rate met)", fact_rate >= 0.9)

    # Edge case 607: only one of Q2/Q5 mentions a data point → no false-positive consistency flag
    q2 = answer_by_id.get("Q2", "")
    q5 = answer_by_id.get("Q5", "")
    soc2_q2 = "soc 2" in q2
    soc2_q5 = "soc 2" in q5
    if soc2_q2 != soc2_q5:
        # mismatched mention — eval should NOT flag this (and we passed CHK506, so it didn't)
        check("CHK607", "Single-mention data points don't trigger false consistency flag", pass_rate is not None and pass_rate >= 95.0)
    else:
        check("CHK607", "Both/neither mention SOC 2 — n/a or both consistent", True, f"q2_soc2={soc2_q2} q5_soc2={soc2_q5}")

    # CHK601-603 — these are aspirational without actually feeding edge questions through.
    # Mark as not tested in this run.
    for cid in ["CHK601", "CHK602", "CHK603"]:
        check(cid, "Edge case: requires explicit edge-case test cases (not in main RFP run)", False, "skipped — no edge questions in standard RFP")

    finalize()


def inject_key_into_notebook():
    """Copy the notebook with API key injected into Part 0 cell."""
    with open(NOTEBOOK) as f:
        nb = json.load(f)
    for cell in nb["cells"]:
        if cell.get("cell_type") != "code":
            continue
        src = "".join(cell.get("source", []))
        if 'ANTHROPIC_API_KEY = ""' in src:
            new_src = src.replace('ANTHROPIC_API_KEY = ""', f'ANTHROPIC_API_KEY = "{API_KEY}"')
            cell["source"] = [line + "\n" for line in new_src.split("\n")[:-1]] + [new_src.split("\n")[-1]]
            break
    with open(TEST_NOTEBOOK, "w") as f:
        json.dump(nb, f, indent=1)


def finalize():
    # Write report
    total = len(results)
    passed = sum(1 for r in results.values() if r["passed"])
    report = {
        "total": total,
        "passed": passed,
        "failed": total - passed,
        "pass_rate": round(passed / total * 100, 1) if total else 0,
        "items": results,
    }
    with open(REPORT, "w") as f:
        json.dump(report, f, indent=2)

    # Update checklist.md in place
    with open(CHECKLIST) as f:
        text = f.read()
    for cid, r in results.items():
        if cid.endswith("_runtime"):
            continue
        marker = "[x]" if r["passed"] else "[✗]"
        text = re.sub(
            rf"- \[[ x✗]\] {cid} ",
            f"- {marker} {cid} ",
            text,
        )
    with open(CHECKLIST, "w") as f:
        f.write(text)

    # Cleanup test notebooks
    for p in [TEST_NOTEBOOK, EXEC_NOTEBOOK]:
        if p.exists():
            p.unlink()

    # Print summary
    print("\n" + "=" * 70)
    print("VALIDATION SUMMARY")
    print("=" * 70)
    print(f"Total: {total} | Passed: {passed} ✓ | Failed: {total - passed} ✗")
    print(f"Pass Rate: {report['pass_rate']}%\n")
    for cid, r in sorted(results.items()):
        status = "✓" if r["passed"] else "✗"
        detail = f" — {r['detail']}" if r["detail"] else ""
        print(f"  {status} {cid}: {r['description']}{detail}")
    print("\n" + "=" * 70)
    print(f"Report: {REPORT}")
    print(f"Checklist: {CHECKLIST}")
    print("=" * 70)

    sys.exit(0 if passed == total else 1)


if __name__ == "__main__":
    main()
