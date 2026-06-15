"""The evaluation harness runs and the metrics behave."""

from walegal_demo.evaluation.runner import run_evaluation


def test_evaluation_runs_and_all_metrics_pass():
    results, scores = run_evaluation()
    assert len(results) == 7
    assert len(scores) == 6
    failed = [s.name for s in scores if not s.passed]
    assert not failed, f"metrics failed: {failed}"


def test_zero_invented_citations_metric_is_perfect():
    _results, scores = run_evaluation()
    m1 = next(s for s in scores if s.name.startswith("M1"))
    assert m1.actual == 1.0
