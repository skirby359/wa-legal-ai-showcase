"""Agent mode: same gate and note as the pipeline, different evidence gathering."""

from walegal_demo.agent import AgentConfig, CorpusTools, run_agent
from walegal_demo.corpus import get_corpus
from walegal_demo.pipeline import negative_history_note
from walegal_demo.provider import MockProvider

WIDGET_Q = "What is unlawful widget operation?"


def _tools_used(result) -> list[str]:
    return [s.name.split("(")[0] for s in result.trace if s.kind == "tool"]


def test_answers_with_search_read_and_follow():
    result = run_agent(WIDGET_Q, get_corpus())
    assert result.outcome == "answered"
    assert result.mode == "agent"
    used = _tools_used(result)
    assert used[0] == "search_authorities"
    assert {"read_authority", "follow_citation"} <= set(used)
    assert "RCW 70.400.010" in result.answer_text
    assert "not legal advice" in result.rendered_text.lower()


def test_citation_graph_has_both_directions():
    tools = CorpusTools(get_corpus())
    cites, cited_by = tools.follow_citation("State v. Northup")
    assert "RCW 70.400.010" in cites
    assert "State v. Meadows" in cited_by  # the overruled case points at the case that overruled it


def test_audit_failure_triggers_one_revision_that_fixes_it():
    result = run_agent(WIDGET_Q, get_corpus(), MockProvider(hallucinate=True))
    assert result.outcome == "answered"
    assert "Fabricated" in result.raw_answer_text
    assert "Fabricated" not in result.answer_text
    assert [s.name for s in result.trace if s.kind == "llm"] == ["draft", "revise"]


def test_a_citation_that_survives_revision_means_could_not_verify():
    result = run_agent(WIDGET_Q, get_corpus(), MockProvider(hallucinate=True, stubborn=True))
    assert result.outcome == "could_not_verify"
    assert result.refused
    assert "State v. Fabricated" in result.rendered_text  # names what failed
    assert result.answer_text == ""


def test_finalize_adds_the_same_negative_history_note():
    q = "What did State v. Meadows hold about network control of a widget?"
    result = run_agent(q, get_corpus(), MockProvider(cite_overruled=True))
    assert result.outcome == "answered"
    assert negative_history_note("overruled") in result.answer_text
    assert any(c.status_annotated for c in result.verification.checks)


def test_tool_cap_forces_the_draft():
    result = run_agent(WIDGET_Q, get_corpus(), cfg=AgentConfig(max_tool_calls=2))
    assert result.tool_calls == 2
    assert any(s.kind == "cap" for s in result.trace)
    assert result.outcome == "answered"


def test_refuses_out_of_scope_like_the_pipeline():
    result = run_agent("How do I bake sourdough bread at home?", get_corpus())
    assert result.outcome == "refused"
    assert run_agent("?!", get_corpus()).outcome == "refused"
