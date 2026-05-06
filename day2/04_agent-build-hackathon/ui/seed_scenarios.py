"""Seed the scenario store with 50 sample RFP scenarios.

Scenarios span 12 fictional clients across 6 verticals (banking,
insurance, healthcare, retail, public sector, fintech). Each scenario
contains 3–6 questions drawn from a question bank, mixed across
categories so the specialist routing exercises all 4 sub-agents.

Idempotent: if scenarios already exist with these seed IDs, they're
skipped (so re-running won't duplicate).
"""

from __future__ import annotations

import json
import random
from pathlib import Path

import storage


# ============================================================
# Question banks per category
# ============================================================

QUESTIONS_TECHNICAL = [
    "Describe your platform's approach to real-time threat detection. What data sources are ingested, and what is the average detection-to-alert latency?",
    "What ML models do you use for anomaly detection, and how are they trained and updated?",
    "How does your platform integrate with cloud workload security (AWS, Azure, GCP)?",
    "Describe your endpoint agent architecture. What is the agent's CPU and memory footprint?",
    "What network telemetry does your platform ingest (NetFlow, IPFIX, packet capture)?",
    "How do you correlate events across endpoints, network, and cloud?",
    "What is your SIEM correlation engine throughput per tenant?",
    "Describe your platform's approach to handling encrypted traffic — do you support TLS inspection?",
    "How does your detection engine handle zero-day threats and previously unseen malware?",
    "What APIs do you expose for SIEM/SOAR integration?",
    "How do you handle data residency requirements for customers operating in the EU? Describe encryption at rest and in transit.",
    "What is your mean time to detect (MTTD) and mean time to respond (MTTR) for known threats?",
    "Describe your platform's deployment model — SaaS, on-prem, hybrid?",
    "How do you handle agent updates? What is your change management process?",
    "What are your platform's high availability and disaster recovery capabilities?",
]

QUESTIONS_COMPLIANCE = [
    "List all compliance certifications your organization currently holds (SOC 2, ISO 27001, FedRAMP, etc.) and the date of most recent audit for each.",
    "Are you SOC 2 Type II certified? When was your last audit and who performed it?",
    "Do you hold FedRAMP Moderate authorization? What is your sponsoring agency?",
    "What is your GDPR compliance posture? Do you offer a Data Processing Agreement?",
    "How do you handle HIPAA-protected health information? Can you provide a Business Associate Agreement?",
    "Are you PCI DSS certified? What level and when was the most recent validation?",
    "Describe your data retention and deletion policies. Are they configurable per tenant?",
    "What is your incident response and breach notification process?",
    "Do you undergo regular third-party penetration testing? Who performs it and how often?",
    "Are you StateRAMP authorized for state and local government deployments?",
    "What is your vendor risk management posture? Can you provide your latest SIG questionnaire?",
    "How do you handle data subject access requests (DSAR) under GDPR?",
    "What audit logs are available to customers? How long are they retained?",
    "Describe your separation-of-duties controls for production infrastructure.",
]

QUESTIONS_PRICING = [
    "Provide per-seat pricing for 500, 1,000, and 5,000 endpoints. Are volume discounts available? Is there a minimum contract term?",
    "What is your pricing structure for the EPP+EDR bundle? Are SIEM and MDR sold separately?",
    "Can you provide a quote for 2,500 endpoints with multi-year commitment?",
    "What discounts are available for educational institutions or non-profits?",
    "Are there professional services costs we should expect on top of the platform pricing?",
    "What is your cancellation policy and contract renewal process?",
    "Do you offer usage-based or consumption-based pricing as an alternative to per-seat?",
    "What payment terms do you offer? Net 30, Net 60, milestone-based?",
    "Can you provide pricing for our 1,200-endpoint deployment? How does mid-tier pricing work?",
    "What is the all-in cost for 5,000 endpoints with EPP+EDR+SIEM+MDR over 3 years?",
    "Are there any setup fees, onboarding charges, or training costs?",
    "What is the cost of additional log retention beyond your default policy?",
]

QUESTIONS_COMPANY = [
    "How many customers do you currently serve in the financial services vertical? Provide 2–3 reference accounts.",
    "What is your customer count in healthcare and what is the average deployment size?",
    "Can you provide reference accounts in the retail or e-commerce vertical?",
    "Describe your company's history, headcount, and funding stage.",
    "What is your customer NPS score? How is it measured?",
    "What is your annual recurring revenue and growth rate?",
    "Who are your top 3 references in the public sector?",
    "How many security analysts/engineers do you employ?",
    "What is your customer renewal/retention rate over the past 24 months?",
    "Describe your global footprint — offices, support centers, data centers.",
    "What strategic technology partnerships do you maintain?",
    "Can you provide 3 case studies relevant to a financial services prospect?",
]


CATEGORY_BANKS = {
    "technical": QUESTIONS_TECHNICAL,
    "compliance": QUESTIONS_COMPLIANCE,
    "pricing": QUESTIONS_PRICING,
    "company-info": QUESTIONS_COMPANY,
}


# ============================================================
# Fictional clients across 6 verticals
# ============================================================

CLIENTS = [
    # Banking
    ("Meridian National Bank",       "banking",          "Tier-1 retail bank, 3,200-endpoint estate, expanding cyber program for 2027"),
    ("Crestview Capital Partners",   "banking",          "Mid-market private bank evaluating endpoint protection consolidation"),
    ("Atlas Federal Credit Union",   "banking",          "Regional credit union, FedRAMP requirements for federal deposit programs"),
    # Insurance
    ("Apex Insurance Group",         "insurance",        "Multi-line insurer, full-platform deployment due for renewal"),
    ("Northstar Mutual",             "insurance",        "Mutual life insurance, GDPR scope for European subsidiaries"),
    # Healthcare
    ("Wellspring Health Network",    "healthcare",       "Regional hospital system, HIPAA + HITRUST scope, EHR integration"),
    ("Heliopolis Pharmaceuticals",   "healthcare",       "Mid-cap pharma, IP protection for clinical trial data"),
    # Retail / e-commerce
    ("Acme Retail",                  "retail",           "National retail chain, 12,000 endpoints across stores + corporate"),
    ("Vertex E-Commerce",            "retail",           "Pure-play DTC, PCI scope across payments stack"),
    # Public sector
    ("Riverside County",             "public-sector",    "County government, StateRAMP requirements, K-12 + utilities scope"),
    # Fintech
    ("Lumen Pay",                    "fintech",          "Payments startup, Series C, scaling SOC 2 program for enterprise sales"),
    ("Quantilis Trading",            "fintech",          "Algorithmic trading firm, low-latency ingestion is critical"),
]


# ============================================================
# Builder
# ============================================================

def _build_questions(rng: random.Random) -> list[dict]:
    """Pick 3–6 questions across categories with at least 2 categories represented."""
    n_questions = rng.randint(3, 6)
    # Decide category mix: at least 2 distinct categories
    categories = list(CATEGORY_BANKS.keys())
    rng.shuffle(categories)
    chosen_cats: list[str] = []
    while len(chosen_cats) < n_questions:
        chosen_cats.append(rng.choice(categories))
    # Ensure at least 2 distinct categories
    if len(set(chosen_cats)) == 1 and len(categories) > 1:
        chosen_cats[-1] = next(c for c in categories if c != chosen_cats[0])
    rng.shuffle(chosen_cats)

    questions: list[dict] = []
    for i, cat in enumerate(chosen_cats):
        bank = CATEGORY_BANKS[cat]
        text = rng.choice(bank)
        questions.append({
            "id": f"Q{i + 1}",
            "category": cat,
            "text": text,
        })
    return questions


def build_seed_scenarios(seed: int = 42) -> list[dict]:
    """Return 50 scenario dicts (not yet persisted)."""
    rng = random.Random(seed)
    scenarios: list[dict] = []
    rfp_year = 2026

    # Scenario themes per client (2–6 scenarios per client to reach 50)
    themes = [
        "Q1 cybersecurity RFP",
        "EDR/EPP refresh evaluation",
        "Compliance addendum questionnaire",
        "Pricing & contract renewal",
        "Architecture deep-dive",
        "Reference + case study request",
        "Vendor risk management review",
        "EU expansion data-residency questionnaire",
        "M&A due-diligence security review",
        "Incident-response readiness assessment",
    ]

    while len(scenarios) < 50:
        for client_name, vertical, blurb in CLIENTS:
            if len(scenarios) >= 50:
                break
            theme = themes[len(scenarios) % len(themes)]
            sid = f"seed-{len(scenarios) + 1:03d}"
            scenarios.append({
                "id": sid,
                "name": f"{client_name} — {theme}",
                "client": client_name,
                "description": f"[{vertical}] {blurb}",
                "questions": _build_questions(rng),
                "tags": ["seed", vertical],
                "rfp_year": rfp_year,
                "_seed": True,
            })
    return scenarios[:50]


def seed(force: bool = False) -> dict:
    """Persist 50 scenarios. Idempotent: skips ones already saved by seed-id."""
    existing_ids = {s["id"] for s in storage.list_scenarios()}
    saved = []
    skipped = []
    for scenario in build_seed_scenarios():
        sid = scenario["id"]
        if sid in existing_ids and not force:
            skipped.append(sid)
            continue
        storage.save_scenario(scenario)
        saved.append(sid)
    return {
        "saved": len(saved),
        "skipped": len(skipped),
        "total": len(saved) + len(skipped),
    }


if __name__ == "__main__":
    import sys
    force = "--force" in sys.argv
    result = seed(force=force)
    print(json.dumps(result, indent=2))
