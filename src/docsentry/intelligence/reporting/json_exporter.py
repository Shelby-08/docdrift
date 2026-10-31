"""Deterministic JSON export of an AnalysisResult."""

import json
from typing import Any

from docsentry.intelligence.models.analysis import AnalysisResult


def _scrub_snippets(node: Any) -> Any:
    if isinstance(node, dict):
        return {k: (None if k == "snippet" else _scrub_snippets(v)) for k, v in node.items()}
    if isinstance(node, list):
        return [_scrub_snippets(v) for v in node]
    return node


def to_json(result: AnalysisResult, *, include_texts: bool = False) -> str:
    data: dict[str, Any] = result.model_dump(mode="json")
    if not include_texts:
        for key in ("facts", "claims", "relationships", "entities", "semantic_changes"):
            data[key] = _scrub_snippets(data[key])
        for claim in data["claims"]:
            claim["original_text"] = ""
        for item in data["ai_review_input"]["items"]:
            if item["kind"] != "finding":
                item["claim_text"] = ""
    return json.dumps(data, sort_keys=True, indent=2, ensure_ascii=False)
