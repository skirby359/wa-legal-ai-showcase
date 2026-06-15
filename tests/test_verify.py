"""The anti-hallucination gate (Stage 6) is the heart of the showcase."""

from walegal_demo.corpus import get_corpus
from walegal_demo.pipeline import run_pipeline
from walegal_demo.provider import MockProvider


def test_hallucinated_citation_is_stripped():
    """A fabricated citation from the model must never reach the user."""
    result = run_pipeline(
        "What is unlawful widget operation?",
        get_corpus(),
        MockProvider(hallucinate=True),
    )
    # The model emitted the fake cite...
    assert "State v. Fabricated" in result.raw_answer_text
    # ...but verify stripped it from the answer the user sees.
    assert "State v. Fabricated" not in result.answer_text
    assert result.verification.citations_stripped >= 1
    assert any("Fabricated" in f for f in result.verification.flags)


def test_grounded_citations_survive():
    result = run_pipeline(
        "What is unlawful widget operation?",
        get_corpus(),
        MockProvider(hallucinate=False),
    )
    assert result.verification.citations_stripped == 0
    assert result.verification.citations_passed >= 1
    assert result.verification.passed


def test_overstatement_is_flagged():
    result = run_pipeline(
        "What are the elements of first-degree unlawful widget operation?",
        get_corpus(),
        MockProvider(overstate=True),
    )
    assert any("overstatement" in f for f in result.verification.flags)
