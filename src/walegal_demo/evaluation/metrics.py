"""Automated evaluation metrics (sanitized subset of the production M1-M10).

The production system computes ten metrics; this demo implements the six that
don't require the full corpus or an LLM judge. Each takes a list of
QuestionResult and returns a MetricScore.
"""

from __future__ import annotations

from walegal_demo.evaluation.types import MetricScore, QuestionResult


def metric_zero_invented_citations(results: list[QuestionResult]) -> MetricScore:
    """M1: No hallucinated citation is ever shown to the user. Target 100%."""
    applicable = [r for r in results if not r.refused and r.citations_checked > 0]
    if not applicable:
        return MetricScore("M1 Zero invented citations shown", 1.0, 1.0, True,
                           "No applicable questions", 0)
    clean = sum(1 for r in applicable if r.citations_invented_shown == 0)
    actual = clean / len(applicable)
    return MetricScore("M1 Zero invented citations shown", 1.0, actual, actual >= 1.0,
                       f"{clean}/{len(applicable)} answers show zero invented citations",
                       len(applicable))


def metric_required_authority_recall(results: list[QuestionResult]) -> MetricScore:
    """M2: Required authorities appear in the evidence. Target >= 90%."""
    total_req = total_found = 0
    for r in results:
        if r.refused:
            continue
        n = len(r.required_authority_found) + len(r.required_authority_missing)
        if n == 0:
            continue
        total_req += n
        total_found += len(r.required_authority_found)
    if total_req == 0:
        return MetricScore("M2 Required authority recall", 0.90, 1.0, True,
                           "No questions with required authorities", 0)
    actual = total_found / total_req
    return MetricScore("M2 Required authority recall", 0.90, actual, actual >= 0.90,
                       f"{total_found}/{total_req} required authorities found", total_req)


def metric_controlling_authority_top5(results: list[QuestionResult]) -> MetricScore:
    """M3: Controlling authority is in the top-5 evidence. Target >= 85%."""
    applicable = [r for r in results if not r.refused and r.has_controlling_authority]
    if not applicable:
        return MetricScore("M3 Controlling authority in top-5", 0.85, 1.0, True,
                           "No questions with controlling authority", 0)
    found = sum(1 for r in applicable if r.controlling_in_top5)
    actual = found / len(applicable)
    return MetricScore("M3 Controlling authority in top-5", 0.85, actual, actual >= 0.85,
                       f"{found}/{len(applicable)} have controlling authority in top-5",
                       len(applicable))


def metric_refusal_accuracy(results: list[QuestionResult]) -> MetricScore:
    """M6: Refuses exactly when it should. Target >= 95%."""
    if not results:
        return MetricScore("M6 Refusal accuracy", 0.95, 1.0, True, "No questions", 0)
    correct = sum(1 for r in results if r.refused == r.expected_refusal)
    actual = correct / len(results)
    fp = sum(1 for r in results if not r.expected_refusal and r.refused)
    fn = sum(1 for r in results if r.expected_refusal and not r.refused)
    detail = f"{correct}/{len(results)} correct"
    if fp:
        detail += f", {fp} false refusals"
    if fn:
        detail += f", {fn} missed refusals"
    return MetricScore("M6 Refusal accuracy", 0.95, actual, actual >= 0.95, detail, len(results))


def metric_response_length(results: list[QuestionResult]) -> MetricScore:
    """M9: Answers stay within length budget. Target >= 90%."""
    applicable = [r for r in results if not r.refused and r.word_count > 0]
    if not applicable:
        return MetricScore("M9 Response length", 0.90, 1.0, True, "No applicable questions", 0)
    within = sum(1 for r in applicable if r.word_count <= 500)
    actual = within / len(applicable)
    return MetricScore("M9 Response length", 0.90, actual, actual >= 0.90,
                       f"{within}/{len(applicable)} within length budget", len(applicable))


def metric_build_disclaimer(results: list[QuestionResult]) -> MetricScore:
    """M10: Every answer carries a disclaimer + build metadata. Target 100%."""
    applicable = [r for r in results if not r.refused]
    if not applicable:
        return MetricScore("M10 Build disclaimer", 1.0, 1.0, True, "No applicable questions", 0)
    present = sum(1 for r in applicable if r.has_disclaimer and r.has_build_metadata)
    actual = present / len(applicable)
    return MetricScore("M10 Build disclaimer", 1.0, actual, actual >= 1.0,
                       f"{present}/{len(applicable)} carry disclaimer + build metadata",
                       len(applicable))


ALL_METRICS = [
    metric_zero_invented_citations,
    metric_required_authority_recall,
    metric_controlling_authority_top5,
    metric_refusal_accuracy,
    metric_response_length,
    metric_build_disclaimer,
]
