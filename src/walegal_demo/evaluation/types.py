"""Evaluation data types (sanitized subset of the production harness)."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class GoldQuestion:
    """One annotated question from the gold set."""

    id: str
    question: str
    category: str
    expected_authorities: list[str] = field(default_factory=list)
    required_authorities: list[str] = field(default_factory=list)
    controlling_authority: str | None = None
    expected_authority_types: list[str] = field(default_factory=list)
    expect_refusal: bool = False
    max_words: int = 250


@dataclass
class QuestionResult:
    """Outcome of running one gold question through the pipeline."""

    question_id: str
    category: str
    refused: bool
    expected_refusal: bool
    outcome: str = "answered"  # answered | refused | could_not_verify
    error: bool = False
    citations_checked: int = 0
    citations_passed: int = 0
    citations_invented_shown: int = 0   # measured on the final answer text
    citations_shown: int = 0            # citations in the final answer text
    negative_unqualified: int = 0       # negative-history cites shown without a warning
    negative_annotated: bool = False    # passed M7 only because the note was added
    tool_calls: int = 0
    llm_calls: int = 0
    required_authority_found: list[str] = field(default_factory=list)
    required_authority_missing: list[str] = field(default_factory=list)
    has_controlling_authority: bool = False
    controlling_in_top5: bool = False
    word_count: int = 0
    has_disclaimer: bool = False
    has_build_metadata: bool = False


@dataclass
class MetricScore:
    """A single metric's score against its target."""

    name: str
    target: float
    actual: float
    passed: bool
    detail: str = ""
    applicable: int = 0
