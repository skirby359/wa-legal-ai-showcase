"""Load the gold evaluation set."""

from __future__ import annotations

import json
from pathlib import Path

from walegal_demo.evaluation.types import GoldQuestion

# data/gold_set.json sits at the repo root.
_DEFAULT_PATH = Path(__file__).resolve().parents[3] / "data" / "gold_set.json"


def load_gold(path: Path | None = None) -> list[GoldQuestion]:
    """Parse the gold set JSON into GoldQuestion objects."""
    path = path or _DEFAULT_PATH
    raw = json.loads(path.read_text(encoding="utf-8"))
    questions = raw["questions"] if isinstance(raw, dict) else raw
    out: list[GoldQuestion] = []
    for q in questions:
        out.append(
            GoldQuestion(
                id=q["id"],
                question=q["question"],
                category=q.get("category", ""),
                expected_authorities=q.get("expected_authorities", []),
                required_authorities=q.get("required_authorities", []),
                controlling_authority=q.get("controlling_authority"),
                expected_authority_types=q.get("expected_authority_types", []),
                expect_refusal=q.get("expect_refusal", False),
                max_words=q.get("max_words", 250),
            )
        )
    return out
