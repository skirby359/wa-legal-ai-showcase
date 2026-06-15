"""End-to-end pipeline behavior."""

from walegal_demo.corpus import get_corpus
from walegal_demo.pipeline import run_pipeline
from walegal_demo.provider import MockProvider


def test_answers_a_statutory_question_with_grounded_cite():
    result = run_pipeline(
        "What is unlawful widget operation under Washington law?", get_corpus()
    )
    assert not result.refused
    assert "RCW 70.400.010" in result.answer_text
    assert "not legal advice" in result.rendered_text.lower()
    assert result.build_id in result.rendered_text


def test_refuses_out_of_scope_question():
    result = run_pipeline("How do I bake sourdough bread?", get_corpus())
    assert result.refused
    assert result.evidence_pack is None


def test_refuses_empty_question():
    result = run_pipeline("?!", get_corpus())
    assert result.refused
