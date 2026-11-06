"""Run the gold set through one arm (pipeline or agent) and score the metrics.

Both arms go through the same scoring code. Production does the same with an
``answerer=`` hook on its harness, so an A/B differs only in how each question
is answered, never in how it is graded.
"""

from __future__ import annotations

from collections.abc import Callable

from walegal_demo.agent import run_agent
from walegal_demo.corpus import get_corpus
from walegal_demo.evaluation.gold import load_gold
from walegal_demo.evaluation.metrics import ALL_METRICS
from walegal_demo.evaluation.types import GoldQuestion, MetricScore, QuestionResult
from walegal_demo.pipeline import extract_citations, run_pipeline, ungrounded_citations
from walegal_demo.provider import LLMProvider, MockProvider
from walegal_demo.types import Authority, PipelineResult

Answerer = Callable[[str, list[Authority], LLMProvider], PipelineResult]

ARMS: dict[str, Answerer] = {
    "baseline": run_pipeline,
    "agent": run_agent,
}


def _score_question(gold: GoldQuestion, result: PipelineResult) -> QuestionResult:
    """Convert one answered (or refused) question into a scored QuestionResult."""
    qr = QuestionResult(
        question_id=gold.id,
        category=gold.category,
        refused=result.refused,
        expected_refusal=gold.expect_refusal,
        outcome=result.outcome,
        tool_calls=result.tool_calls,
        llm_calls=result.llm_calls,
    )

    if result.refused:
        return qr

    evidence = result.evidence_pack
    verification = result.verification
    pack_cites = [p.authority.canonical_cite for p in evidence.passages] if evidence else []

    # M2: required authorities present in evidence pack.
    for req in gold.required_authorities:
        if req in pack_cites:
            qr.required_authority_found.append(req)
        else:
            qr.required_authority_missing.append(req)

    # M3: controlling authority in top-5 evidence.
    qr.has_controlling_authority = gold.controlling_authority is not None
    if qr.has_controlling_authority:
        qr.controlling_in_top5 = gold.controlling_authority in pack_cites[:5]

    # M1: measured on the text the user sees, not assumed from the strip step.
    qr.citations_shown = len(extract_citations(result.answer_text))
    qr.citations_invented_shown = len(ungrounded_citations(result.answer_text, evidence))

    # M7: negative-history authority shown without a warning.
    if verification:
        qr.citations_checked = verification.citations_checked
        qr.citations_passed = verification.citations_passed
        qr.negative_unqualified = sum(
            1 for c in verification.checks if c.resolved and not c.status_ok
        )
        qr.negative_annotated = any(c.status_annotated for c in verification.checks)

    # M9 / M10.
    qr.word_count = len(result.answer_text.split())
    qr.has_disclaimer = "not legal advice" in result.rendered_text.lower()
    qr.has_build_metadata = "build " in result.rendered_text.lower()
    return qr


def run_evaluation(
    arm: str = "baseline", provider: LLMProvider | None = None
) -> tuple[list[QuestionResult], list[MetricScore]]:
    """Run every gold question through one arm and compute all metrics."""
    answerer = ARMS[arm]
    corpus = get_corpus()
    gold = load_gold()
    provider = provider or MockProvider()

    results: list[QuestionResult] = []
    for q in gold:
        results.append(_score_question(q, answerer(q.question, corpus, provider)))

    scores = [metric(results) for metric in ALL_METRICS]
    return results, scores
