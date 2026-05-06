# Testing Guide — RFP Agent Hackathon

---

## Overview

A comprehensive eval framework that tests:
1. **Standard functionality** — Accuracy, sources, confidence, quality
2. **Edge cases** — Ambiguous questions, out-of-scope queries, typos
3. **Consistency** — Cross-answer coherence
4. **Robustness** — Graceful degradation under adverse conditions

**Goal:** 52+ assertions across standard and edge cases, ≥95% pass rate.

---

## Standard Test Suite (Parts 5–7)

### 1. Factual Accuracy Tests

Test that answers contain specific data points from the knowledge base.

```python
def test_standard_accuracy(framework: EvalFramework):
    """Test accuracy of specific data points."""
    
    # Q1: Latency numbers
    framework.assert_specific_data("Q1", "2.3 seconds", "Q1_latency_signature")
    framework.assert_specific_data("Q1", "18 seconds", "Q1_latency_behavioral")
    framework.assert_specific_data("Q1", "50,000", "Q1_siem_eps")
    
    # Q2: Certification dates
    framework.assert_specific_data("Q2", "December 2024", "Q2_soc2_date")
    framework.assert_specific_data("Q2", "June 2024", "Q2_fedramp_date")
    framework.assert_specific_data("Q2", "January 2025", "Q2_stateRamp_date")
    
    # Q3: Pricing
    framework.assert_specific_data("Q3", "$18/seat/month", "Q3_pricing_500")
    framework.assert_specific_data("Q3", "39%", "Q3_discount_5000")
    framework.assert_specific_data("Q3", "12 months", "Q3_min_term")
    
    # Q4: Customer references
    framework.assert_specific_data("Q4", "47 customers", "Q4_customer_count")
    framework.assert_specific_data("Q4", "Meridian", "Q4_ref_meridian")
    framework.assert_specific_data("Q4", "Crestview", "Q4_ref_crestview")
    
    # Q5: Encryption
    framework.assert_specific_data("Q5", "AES-256-GCM", "Q5_encryption_rest")
    framework.assert_specific_data("Q5", "TLS 1.3", "Q5_encryption_transit")
    framework.assert_specific_data("Q5", "GDPR", "Q5_gdpr")
```

**Expected:** 15 assertions, all pass.

### 2. Source Attribution Tests

Verify that every answer cites at least one source.

```python
def test_source_attribution(framework: EvalFramework):
    """Test that all answers cite sources."""
    for qid in ["Q1", "Q2", "Q3", "Q4", "Q5"]:
        framework.assert_has_sources(qid, min_sources=1)
```

**Expected:** 5 assertions, all pass.  
**Why important:** Buyers need traceability; agents without sources are not credible.

### 3. Confidence Calibration Tests

Verify that confidence values are valid (high/medium/low) and appropriate.

```python
def test_confidence_calibration(framework: EvalFramework):
    """Test confidence values are valid and calibrated."""
    for qid in ["Q1", "Q2", "Q3", "Q4", "Q5"]:
        framework.assert_confidence_valid(qid)
```

**Expected:** 5 assertions, all pass.  
**Why important:** Confidence helps humans prioritize which answers to review.

### 4. Answer Quality Tests

Verify answers are substantial (not empty, no placeholders).

```python
def test_answer_quality(framework: EvalFramework):
    """Test basic answer quality metrics."""
    for qid in ["Q1", "Q2", "Q3", "Q4", "Q5"]:
        framework.assert_no_empty_answer(qid)  # >50 chars
        framework.assert_no_placeholder_text(qid)  # No TODO, TBD, etc.
```

**Expected:** 10 assertions, all pass.  
**Checks:**
- Answers are not empty (>50 characters)
- No placeholder text (TODO, PLACEHOLDER, TBD, [INSERT...])

### 5. Consistency Tests

Verify cross-answer coherence.

```python
def test_consistency(framework: EvalFramework):
    """Test cross-answer consistency."""
    
    # Q2 and Q5 should both mention ISO 27001
    q2_answer = framework.answers_map.get("Q2", {}).get('answer', '')
    q5_answer = framework.answers_map.get("Q5", {}).get('answer', '')
    
    q2_has_iso = "ISO 27001" in q2_answer
    q5_has_iso = "ISO 27001" in q5_answer
    
    # At least one should mention it
    framework.assert_true(q2_has_iso or q5_has_iso, "consistency_iso27001_mentioned")
    
    # Both should mention SOC 2
    framework.assert_contains(q2_answer, "SOC 2", "consistency_soc2_in_q2", "Q2")
    framework.assert_contains(q5_answer, "SOC 2", "consistency_soc2_in_q5", "Q5")
```

**Expected:** 3 assertions, all pass.  
**Why important:** Inconsistencies (e.g., Q2 says "Dec 2024" but Q5 says "Dec 2023") are the #1 quality issue in RFP responses.

---

## Edge Case Test Suite (Part 6)

### Test Cases

| ID | Input | Expected | Category |
|----|-------|----------|----------|
| E1 | "Tell us about your stuff." | Medium/low confidence + flags | Ambiguous |
| E2 | "What is the meaning of life?" | Low confidence + flags | Out-of-scope |
| E3 | "Do you encrypt data?" | Partial match → retrieves encryption docs | Partial match |
| E4 | "Tell us about EU compliance and encryption" | Multi-category match | Multiple categories |
| E5 | "Wat iz ur pricng for 500 endpointes?" | Typo recovery via keyword matching | Typo resilience |

### Edge Case Tests

```python
def test_edge_cases(framework: EvalFramework):
    """Test agent behavior on edge cases."""
    
    edge_cases = [
        {"id": "E1", "text": "Tell us about your stuff.", "category": "technical"},
        {"id": "E2", "text": "What is the meaning of life?", "category": "technical"},
        {"id": "E3", "text": "Do you encrypt data?", "category": "technical"},
        {"id": "E4", "text": "EU compliance and encryption", "category": "compliance"},
        {"id": "E5", "text": "Wat iz ur pricng for 500 endpointes?", "category": "pricing"},
    ]
    
    edge_answers = process_edge_cases(edge_cases)
    framework.register_answers(edge_answers)
    
    # All should have valid structure
    for ans in edge_answers:
        qid = ans.get('question_id')
        framework.assert_confidence_valid(qid)
        framework.assert_no_empty_answer(qid)
    
    # Ambiguous/OOO should be low-confidence + flagged
    for qid in ["E1", "E2"]:
        conf = framework.answers_map.get(qid, {}).get('confidence')
        is_cautious = conf in ['medium', 'low']
        framework.assert_true(is_cautious, f"{qid}_cautious_confidence")
        
        has_flags = len(framework.answers_map.get(qid, {}).get('flags', [])) > 0
        framework.assert_true(has_flags, f"{qid}_has_flags")
    
    # Partial match and typos should still produce answers
    for qid in ["E3", "E4", "E5"]:
        ans_length = len(framework.answers_map.get(qid, {}).get('answer', ''))
        framework.assert_true(ans_length > 50, f"{qid}_answer_substantial")
```

**Expected:** 13 assertions.  
**Why important:** Real RFPs have ambiguous questions, typos, and out-of-scope requests. The agent must handle them gracefully.

---

## Running Tests

### Quick Run
```bash
python3 eval.py
```

**Output:**
```
======================================================================
RFP AGENT COMPREHENSIVE EVAL FRAMEWORK
======================================================================

[STANDARD] Testing factual accuracy...
[STANDARD] Testing source attribution...
[STANDARD] Testing confidence calibration...
[STANDARD] Testing answer quality...
[STANDARD] Testing cross-answer consistency...
[EDGE CASES] Testing ambiguous/edge case questions...

======================================================================
EVAL FRAMEWORK RESULTS
======================================================================
Total Tests: 52
Passed: 52 ✓
Failed: 0 ✗
Pass Rate: 100.0%

✓ Q1: 7/7 passed
✓ Q2: 8/8 passed
✓ Q3: 7/7 passed
✓ Q4: 7/7 passed
✓ Q5: 8/8 passed
✓ E1: 2/2 passed
✓ E2: 2/2 passed
✓ E3: 2/2 passed
✓ E4: 2/2 passed
✓ E5: 2/2 passed
======================================================================

✓ Detailed results saved to eval_results.json
```

### Running Specific Test Suite
```python
# Standard tests only
test_standard_accuracy(framework)
test_source_attribution(framework)

# Edge cases only
test_edge_cases(framework)
```

### Parsing Results
```python
import json

with open('eval_results.json', 'r') as f:
    results = json.load(f)

# Summary
print(f"Pass rate: {results['passed'] / (results['passed'] + results['failed']) * 100:.1f}%")

# By question
by_q = {}
for assertion in results['assertions']:
    q = assertion['question']
    if q not in by_q:
        by_q[q] = {'passed': 0, 'failed': 0}
    if assertion['passed']:
        by_q[q]['passed'] += 1
    else:
        by_q[q]['failed'] += 1

for q in sorted(by_q.keys()):
    print(f"{q}: {by_q[q]['passed']}/{by_q[q]['passed'] + by_q[q]['failed']} passed")
```

---

## Test Failure Scenarios

### Scenario 1: Missing Specific Data Point

**Failure:** Q3 doesn't mention "$18/seat/month"  
**Root cause:** Agent didn't retrieve pricing KB document or didn't extract specific number  
**Debugging:**
```python
# Check what agent retrieved
print(f"Q3 answer: {answers[2]['answer'][:200]}...")
print(f"Q3 sources: {answers[2]['sources']}")

# If pricing source not retrieved: KB search failed
# → Try broader search terms in prompt
```

**Fix:** Update system prompt to explicitly ask for pricing tiers:
```python
system_prompt += "\nFor pricing questions: always include specific per-seat rates for each tier."
```

### Scenario 2: Low Confidence When Expected High

**Failure:** Q1 marked medium/low confidence despite good KB match  
**Root cause:** Agent flagged insufficient KB data (but data exists)  
**Debugging:**
```python
# Check flags
print(f"Q1 flags: {answers[0]['flags']}")

# If flags mention missing info, KB retrieval may have failed
search_results = search_knowledge_base("threat detection latency", category="technical")
print(f"Search results: {len(search_results)}")
```

**Fix:** Improve search or update system prompt to be less conservative:
```python
system_prompt += "\nIf you find relevant sources, mark as 'high' confidence even if not exhaustive."
```

### Scenario 3: Contradictory Information Across Answers

**Failure:** Q2 says "SOC 2 audited Dec 2024" but Q5 says "Sep 2024"  
**Root cause:** Consistency review didn't catch; agent retrieved different KB docs  
**Debugging:**
```python
q2 = answers[1]['answer']
q5 = answers[4]['answer']

# Find contradictions
import re
q2_dates = re.findall(r'\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]* \d{4}\b', q2, re.I)
q5_dates = re.findall(r'\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]* \d{4}\b', q5, re.I)

print(f"Q2 dates: {q2_dates}")
print(f"Q5 dates: {q5_dates}")
```

**Fix:** Improve KB consistency (single source of truth) or have Claude validate dates:
```python
# Add validation step after drafting:
"Before finalizing, double-check that cert dates match across all questions."
```

### Scenario 4: Edge Case Not Handled Gracefully

**Failure:** E2 (out-of-scope) returns high-confidence answer instead of low  
**Root cause:** Agent didn't recognize question was out of domain  
**Fix:** Add explicit OOO check to system prompt:
```python
system_prompt += """
If the question is outside Helios' domain (e.g., "what is the meaning of life?"):
- Mark confidence as 'low'
- Add flag: "This question is outside the scope of a cybersecurity platform."
- Return a minimal answer explaining the limitation.
"""
```

---

## Test Metrics to Track

| Metric | Target | Red Flag |
|--------|--------|----------|
| Accuracy assertions pass | 100% | <95% |
| Source attribution | 100% of answers | Any answer without source |
| Confidence valid | 100% | Any invalid value |
| Answer quality | 100% | Empty answer or placeholder |
| Consistency score | High | Medium or low |
| Edge cases handled | 100% valid structure | JSON parse errors |

---

## Iteration & Improvement

### After First Run
1. **Identify failures** — Which assertions failed?
2. **Group by cause** — KB retrieval issue? Prompt issue? Tool use issue?
3. **Fix root cause** — Don't patch individual assertions; fix underlying problem
4. **Re-run** — Ensure fix works for all related assertions

### Example Iteration
```
Run 1: Q3 pricing missing → Improve search query in prompt
Run 2: Q2 cert dates wrong → Consolidate KB sources
Run 3: E1 not low-confidence → Add OOO handling to system prompt
Run 4: All pass → Done!
```

---

## Checklist for Complete Testing

- [ ] Standard accuracy tests pass (15 assertions)
- [ ] Source attribution tests pass (5 assertions)
- [ ] Confidence calibration tests pass (5 assertions)
- [ ] Answer quality tests pass (10 assertions)
- [ ] Consistency tests pass (3 assertions)
- [ ] Edge case tests pass (13 assertions)
- [ ] Pass rate ≥95%
- [ ] No placeholder text in any answer
- [ ] All answers >50 characters
- [ ] All sources properly attributed
- [ ] JSON output is valid
- [ ] eval_results.json generated

---

## Advanced Testing

### Load Testing
Test agent behavior with 20+ questions (realistic RFP size):
```python
large_rfp = [
    {"id": f"Q{i}", "text": f"Question {i}", "category": random.choice(categories)}
    for i in range(1, 21)
]

start = time.time()
answers = process_rfp(large_rfp)
elapsed = time.time() - start

print(f"20 questions in {elapsed:.1f}s ({elapsed/20:.1f}s per question)")
assert elapsed < 120, "RFP should complete in <2 minutes"
```

### Stress Testing
Provide incomplete or malformed KB:
```python
# Remove a critical KB document
KNOWLEDGE_BASE.pop("compliance_certs")

# Run evals
# Expected: Q2 marked medium/low confidence
# Expected: Q2 flags indicate missing compliance data
```

### Regression Testing
After each change to prompts or KB:
```bash
# Run evals
python eval.py

# Compare to baseline
diff eval_results.json baseline_results.json

# Should have ≥same number of passes
```

