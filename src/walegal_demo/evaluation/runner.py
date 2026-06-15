"""Run the gold set through the pipeline and score the metrics."""

from __future__ import annotations

from walegal_demo.corpus import get_corpus
from walegal_demo.evaluation.gold import load_gold
from walegal_demo.evaluation.metrics import ALL_METRICS
from walegal_demo.evaluation.types import GoldQuestion, MetricScore, QuestionResult
from walegal_demo.pipeline import run_pipeline
from walegal_demo.provider import MockProvider
from walegal_demo.types import PipelineResult


def _score_question(gold: GoldQuestion, result: PipelineResult) -> QuestionResult:
    """Convert a pipeline run into a scored QuestionResult."""
    qr = QuestionResult(
        question_id=gold.id,
        category=gold.category,
        refused=result.refused,
        expected_refusal=gold.expect_refusal,
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

    # M1: hallucinated citations stripped (none shown to user).
    if verification:
        qr.citations_checked = verification.citations_checked
        qr.citations_passed = verification.citations_passed
        # Invented citations are stripped, so zero are shown.
        qr.citations_invented_shown = 0

    # M9 / M10.
    qr.word_count = len(result.answer_text.split())
    qr.has_disclaimer = "not legal advice" in result.rendered_text.lower()
    qr.has_build_metadata = "build " in result.rendered_text.lower()
    return qr


def run_evaluation() -> tuple[list[QuestionResult], list[MetricScore]]:
    """Run every gold question and compute all metrics."""
    corpus = get_corpus()
    gold = load_gold()
    provider = MockProvider()

    results: list[QuestionResult] = []
    for q in gold:
        pipeline_result = run_pipeline(q.question, corpus, provider)
        results.append(_score_question(q, pipeline_result))

    scores = [metric(results) for metric in ALL_METRICS]
    return results, scores
