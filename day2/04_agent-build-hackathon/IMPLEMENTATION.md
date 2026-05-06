# Implementation Guide — RFP Agent Hackathon

---

## Part 5: Process All RFP Questions

### What to Build
A `process_rfp()` function that takes a list of RFP questions and returns structured answers.

### Approach: Sequential Processing
The simplest and most reliable approach for a hackathon:

```python
def process_rfp(questions: list[dict]) -> list[dict]:
    """Process a full RFP questionnaire and return structured answers."""
    answers = []
    
    for q in questions:
        print(f"Processing {q['id']}...", end=" ", flush=True)
        
        # Use the Level 0 agent (answer_single_question) on each question
        result = answer_single_question(
            question_id=q['id'],
            question_text=q['text'],
            category=q['category']
        )
        
        answers.append(result)
        print("✓")
    
    return answers
```

### Why This Works
1. **Reuses existing logic** — `answer_single_question()` is already tested (Part 4)
2. **Easy to debug** — Each question's tool use loop is independent
3. **Resilient** — If one question fails, others still run
4. **Parallelizable** — Later: could use `concurrent.futures` for speedup

### Alternative: Batch Processing
Send all questions in one prompt and let Claude call the tool multiple times:

```python
def process_rfp_batch(questions: list[dict]) -> list[dict]:
    """Process all questions in one Claude call."""
    prompt = "Answer all these RFP questions:\n\n"
    for q in questions:
        prompt += f"{q['id']}: {q['text']}\n"
    
    # Single call, but harder to control output
    # Use only if you want speed over reliability
```

**Tradeoff:** Faster but harder to ensure JSON structure for each answer.

---

## Part 6: Consistency Review Step

### What to Build
A `review_answers()` function that:
1. Takes all drafted answers
2. Sends them to Claude for cross-answer analysis
3. Returns issues, consistency score, recommendations

### Implementation

```python
def review_answers(answers: list[dict]) -> dict:
    """Review all drafted answers for cross-question consistency."""
    
    # Format all answers for Claude
    answers_text = json.dumps(answers, indent=2)
    
    review_prompt = f"""Review these RFP answers for consistency across questions.

{answers_text}

Check for:
1. Contradictions in dates or numbers (e.g., Q2 says "Dec 2024" but Q5 says "Dec 2023")
2. Inconsistent tone, level of detail, or specificity
3. Missing cross-references (e.g., Q2 mentions ISO 27001 but Q5 doesn't)
4. Incomplete or vague answers
5. Source attribution issues (answers without sources)

Return a JSON report:
{{
    "issues": [
        "Issue 1: description",
        "Issue 2: description"
    ],
    "consistency_score": "high|medium|low",
    "by_question": {{
        "Q1": "assessment",
        "Q2": "assessment"
    }},
    "recommendations": [
        "Recommendation 1",
        "Recommendation 2"
    ]
}}"""
    
    response = client.messages.create(
        model="claude-opus-4-7",
        max_tokens=1024,
        messages=[{"role": "user", "content": review_prompt}]
    )
    
    # Parse JSON from response
    text = response.content[0].text
    if "```json" in text:
        text = text.split("```json")[1].split("```")[0]
    elif "```" in text:
        text = text.split("```")[1].split("```")[0]
    
    return json.loads(text.strip())
```

### Key Design Points
- **No tools in review step** — Just analysis, no KB search needed
- **Full answer context** — Claude sees all answers to find contradictions
- **Structured output** — Returned as JSON for downstream processing
- **Human-readable format** — Issues, recommendations are actionable

### What Claude Should Catch
- Date contradictions: Q2 (Dec 2024 SOC2) vs. Q5 (mentions Sep 2024 PCI DSS)
- Inconsistent references: One Q mentions FedRAMP, another doesn't
- Tone shifts: Q1 very detailed, Q4 very brief
- Missing attribution: Answers with no sources

---

## Part 7: Export Final Output

### Structure
```python
final_output = {
    "rfp_name": "Helios Security — Sample RFP",
    "total_questions": len(RFP_QUESTIONS),
    "answers": all_answers,  # List of answer objects
    "consistency_review": review,  # Review report
    "metadata": {
        "model": "claude-opus-4-7",
        "knowledge_base_entries": len(KNOWLEDGE_BASE),
        "timestamp": datetime.now().isoformat()
    }
}
```

### Export to JSON
```python
with open('rfp_response.json', 'w') as f:
    json.dump(final_output, f, indent=2)

print(f"✓ RFP response exported to rfp_response.json")
```

### What the Buyer Sees
```json
{
  "rfp_name": "...",
  "answers": [
    {
      "question_id": "Q1",
      "answer": "Detailed answer with specific numbers and examples...",
      "sources": ["Helios Platform Architecture Doc v4.2"],
      "confidence": "high"
    },
    ...
  ],
  "consistency_review": {
    "issues": [],
    "consistency_score": "high",
    "recommendations": [...]
  }
}
```

This is a **polished, ready-to-ship deliverable** that a solutions engineer can copy-paste into their RFP template and send to the prospect with minimal edits.

---

## Part 8: Eval Assertions (Stretch)

### What to Test

| Category | Assertion | Example |
|----------|-----------|---------|
| **Accuracy** | Specific numbers present | Q3 includes "$18/seat/month" |
| **Attribution** | Every answer has sources | `len(answer['sources']) > 0` |
| **Consistency** | No contradictions | Q2 and Q5 dates match |
| **Confidence** | Valid and calibrated | Confidence in ["high", "medium", "low"] |
| **Structure** | JSON is well-formed | All required fields present |
| **Quality** | Answers substantial | `len(answer) > 50 chars` |
| **Edge cases** | Graceful handling | Ambiguous Q marked low confidence + flagged |

### Minimal Test Suite

```python
def run_evals(answers: list[dict]) -> dict:
    """Run quality assertions."""
    results = {"passed": 0, "failed": 0, "details": []}
    
    for ans in answers:
        # Test 1: Has sources
        has_sources = len(ans.get("sources", [])) > 0
        results["details"].append({"q": ans["question_id"], "test": "has_sources", "passed": has_sources})
        
        # Test 2: Valid confidence
        valid_conf = ans.get("confidence") in ["high", "medium", "low"]
        results["details"].append({"q": ans["question_id"], "test": "valid_confidence", "passed": valid_conf})
        
        # Test 3: Answer length
        long_enough = len(ans.get("answer", "")) > 50
        results["details"].append({"q": ans["question_id"], "test": "answer_length", "passed": long_enough})
        
        results["passed"] += sum(1 for d in results["details"] if d["passed"])
        results["failed"] += sum(1 for d in results["details"] if not d["passed"])
    
    return results
```

### Advanced: Specific Data Point Assertions

```python
# Q1: Must include latency numbers
assert "2.3 seconds" in answers[0]["answer"], "Q1 missing latency"
assert "18 seconds" in answers[0]["answer"], "Q1 missing behavioral latency"

# Q3: Must include pricing tiers
assert "$18/seat" in answers[2]["answer"], "Q3 missing 500-seat pricing"
assert "39%" in answers[2]["answer"], "Q3 missing 5000-seat discount"

# Q5: Must mention EU compliance
assert "EU" in answers[4]["answer"] or "GDPR" in answers[4]["answer"], "Q5 missing EU mention"
```

### Edge Case Assertions

```python
# Ambiguous questions should be low-confidence
assert edge_answers[0]["confidence"] in ["medium", "low"], "Ambiguous Q not flagged"

# Out-of-scope should have flags
assert len(edge_answers[1]["flags"]) > 0, "Out-of-scope Q not flagged"

# All should return valid JSON structure
for ans in edge_answers:
    assert "question_id" in ans, f"Missing question_id: {ans}"
    assert "answer" in ans, f"Missing answer: {ans}"
    assert "sources" in ans, f"Missing sources: {ans}"
    assert "confidence" in ans, f"Missing confidence: {ans}"
```

### Running Tests

```python
if __name__ == "__main__":
    results = run_evals(all_answers)
    
    print(f"Passed: {results['passed']}")
    print(f"Failed: {results['failed']}")
    
    for detail in results["details"]:
        status = "✓" if detail["passed"] else "✗"
        print(f"{status} {detail['q']}: {detail['test']}")
    
    # Exit with error if any failed
    if results["failed"] > 0:
        exit(1)
```

---

## Debugging Tips

### Agent Loop Issues
**Problem:** Agent never stops (keeps calling tools)  
**Solution:** Add max_turns limit; print tool calls for visibility
```python
print(f"Turn {turn}: tool_use={response.stop_reason == 'tool_use'}")
if turn >= max_turns:
    print("Max turns reached; returning partial answer")
```

### JSON Parsing Errors
**Problem:** Claude wraps JSON in markdown code blocks  
**Solution:** Strip markdown before parsing
```python
text = response.content[0].text
if "```json" in text:
    text = text.split("```json")[1].split("```")[0]
json.loads(text.strip())
```

### Tool Call Failures
**Problem:** Search returns no results for a query  
**Solution:** Expand query terms; Claude should retry with different keywords
```python
# Claude will naturally broaden search if first attempt returns empty
# Prompts should encourage: "If search returns no results, try broader terms"
```

### Confidence Calibration
**Problem:** All answers marked "high" confidence  
**Solution:** Update system prompt to be more conservative
```python
# Better prompt:
"If the knowledge base lacks info to answer fully, mark as 'medium' or 'low' "
"and explain in flags what's missing."
```

---

## Performance Tips

### Optimize for Speed
1. **Parallel processing:** Use `concurrent.futures.ThreadPoolExecutor` to answer multiple questions at once
2. **Cache KB searches:** If same search called twice, reuse result
3. **Batch review:** Send all 5 answers for review in one call (not sequential)

### Optimize for Quality
1. **Multi-pass refinement:** Draft → review → refine → re-review
2. **Iterative improvements:** If review finds issues, ask Claude to fix them
3. **Human-in-the-loop:** Have solutions engineer flag confusing answers for agent to improve

---

## Production Considerations

### At Scale (100+ RFPs/quarter)
- **KB management:** Integrate with Confluence API for live KB updates
- **Semantic search:** Add embeddings (OpenAI or open-source) for better retrieval
- **Caching:** Store answers to FAQs to speed up common questions
- **Metrics:** Track time saved, quality score per question, human edit count
- **Feedback loop:** Learn from human corrections to improve prompts

### Cost Management
- **Model selection:** Opus is best quality but most expensive; consider Sonnet for cost-saving
- **Token optimization:** Shorter KB summaries, more selective search results
- **Caching:** Use prompt caching to reuse KB context across multiple RFPs

---

## Checklists

### Before Demo
- [ ] All 5 questions answered
- [ ] All answers have sources
- [ ] Consistency review runs without errors
- [ ] JSON output is valid
- [ ] No placeholder text or TODOs
- [ ] Confidence values are appropriate
- [ ] Evals pass (if built)

### After Demo
- [ ] Save output to `rfp_response.json`
- [ ] Save eval results to `eval_results.json`
- [ ] Document design decisions in comments
- [ ] Test on 2–3 edge cases manually
- [ ] Prepare retrospective (what worked, what's next)

