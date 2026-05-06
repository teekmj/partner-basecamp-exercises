"""Search across KB entries + saved scenarios + scenario results.

Same scoring approach as agent_core.retrieve (token overlap), but
indexes across multiple source types and returns mixed results.
"""

from __future__ import annotations

import re
from typing import Iterable

from agent_core import KNOWLEDGE_BASE
from storage import list_scenarios, get_scenario


def _tokens(text: str) -> set[str]:
    return set(re.findall(r"\w+", (text or "").lower()))


def _score(query_terms: set[str], text: str) -> int:
    return len(query_terms & _tokens(text))


def search(query: str, types: Iterable[str] | None = None, limit: int = 20) -> list[dict]:
    """Search across multiple sources.

    types: subset of {"kb", "scenario", "answer"} (default: all)
    Each result has: type, score, title, snippet, location
    """
    query = (query or "").strip()
    if not query:
        return []
    if types is None:
        types = {"kb", "scenario", "answer"}
    types = set(types)

    qt = _tokens(query)
    if not qt:
        return []

    results: list[dict] = []

    # KB entries
    if "kb" in types:
        for kid, entry in KNOWLEDGE_BASE.items():
            text = entry["content"] + " " + " ".join(entry.get("tags", []))
            score = _score(qt, text)
            if score > 0:
                results.append({
                    "type": "kb",
                    "score": score,
                    "title": entry["source"],
                    "snippet": _snippet(entry["content"], qt),
                    "location": f"KB:{kid}",
                    "tags": entry.get("tags", []),
                })

    # Scenarios + answers
    if "scenario" in types or "answer" in types:
        for s_meta in list_scenarios():
            sid = s_meta["id"]
            full = get_scenario(sid)
            if not full:
                continue

            # Scenario itself: name, description, question text
            if "scenario" in types:
                text = " ".join([
                    full.get("name", ""),
                    full.get("description", ""),
                    full.get("client", ""),
                    " ".join(q.get("text", "") for q in full.get("questions", [])),
                ])
                score = _score(qt, text)
                if score > 0:
                    results.append({
                        "type": "scenario",
                        "score": score,
                        "title": f"{full.get('name', 'Scenario')} ({full.get('client', '?')})",
                        "snippet": _snippet(full.get("description") or text, qt),
                        "location": f"scenario:{sid}",
                        "tags": [full.get("client", "")],
                    })

            # Individual answers within the scenario's last result
            if "answer" in types and full.get("result"):
                for ans in full["result"].get("answers", []):
                    text = ans.get("answer", "")
                    score = _score(qt, text)
                    if score > 0:
                        results.append({
                            "type": "answer",
                            "score": score,
                            "title": f"{full.get('name', 'Scenario')} → {ans.get('question_id', '?')}",
                            "snippet": _snippet(text, qt),
                            "location": f"scenario:{sid}/{ans.get('question_id')}",
                            "tags": [ans.get("category", ""), f"confidence:{ans.get('confidence', '?')}"],
                        })

    results.sort(key=lambda r: r["score"], reverse=True)
    return results[:limit]


def _snippet(text: str, query_terms: set[str], window: int = 80) -> str:
    """Return a snippet of `text` centered on the first matching term, if any."""
    if not text:
        return ""
    lower = text.lower()
    best = -1
    for term in query_terms:
        idx = lower.find(term)
        if idx != -1 and (best == -1 or idx < best):
            best = idx
    if best == -1:
        return text[: window * 2] + ("…" if len(text) > window * 2 else "")
    start = max(0, best - window)
    end = min(len(text), best + window)
    snippet = text[start:end]
    if start > 0:
        snippet = "…" + snippet
    if end < len(text):
        snippet = snippet + "…"
    return snippet
