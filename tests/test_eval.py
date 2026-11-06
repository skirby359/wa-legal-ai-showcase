"""The evaluation harness runs, the metrics behave, and both arms are scored alike."""

import pytest

from walegal_demo.evaluation.metrics import (
    metric_negative_authority_avoidance,
    metric_zero_invented_citations,
)
from walegal_demo.evaluation.runner import run_evaluation
from walegal_demo.evaluation.types import QuestionResult
from walegal_demo.provider import MockProvider


@pytest.mark.parametrize("arm", ["baseline", "agent"])
def test_evaluation_runs_and_all_metrics_pass(arm):
    results, scores = run_evaluation(arm)
    assert len(results) == 8
    assert len(scores) == 7
    failed = [s.name for s in scores if not s.passed]
    assert not failed, f"metrics failed: {failed}"


def test_zero_invented_citations_metric_is_perfect():
    _results, scores = run_evaluation()
    m1 = next(s for s in scores if s.name.startswith("M1"))
    assert m1.actual == 1.0


def _answered(**kw) -> QuestionResult:
    return QuestionResult(question_id="x", category="c", refused=False,
                          expected_refusal=False, citations_checked=2, **kw)


def test_m1_fails_when_an_invented_citation_is_shown():
    """M1 is measured, so it can fail (it used to be assumed)."""
    score = metric_zero_invented_citations([_answered(), _answered(citations_invented_shown=1)])
    assert not score.passed
    assert score.actual == 0.5


def test_m7_counts_answers_saved_by_the_note():
    score = metric_negative_authority_avoidance([
        _answered(), _answered(negative_annotated=True), _answered(negative_unqualified=1),
    ])
    assert score.actual == pytest.approx(2 / 3)
    assert "1 only because of the note" in score.detail


def test_neg_question_needs_the_note_in_both_arms():
    for arm in ("baseline", "agent"):
        results, _ = run_evaluation(arm, MockProvider(cite_overruled=True))
        neg = next(r for r in results if r.question_id == "neg-008")
        assert neg.negative_annotated and neg.negative_unqualified == 0


def test_stubborn_hallucination_costs_the_agent_refusal_accuracy():
    """The strict audit gate refuses; the pipeline strips and answers."""
    provider = MockProvider(hallucinate=True, stubborn=True)
    base, base_scores = run_evaluation("baseline", provider)
    agent, agent_scores = run_evaluation("agent", provider)
    assert all(r.outcome != "could_not_verify" for r in base)
    assert any(r.outcome == "could_not_verify" for r in agent)
    m6 = {s.name: s for s in agent_scores}["M6 Refusal accuracy"]
    assert not m6.passed
