"""The anti-hallucination gate (Stage 6) is the heart of the showcase."""

from walegal_demo.corpus import get_corpus
from walegal_demo.pipeline import (
    extract_citations,
    negative_history_note,
    pack,
    rerank,
    retrieve,
    rewrite,
    run_pipeline,
    verify,
)
from walegal_demo.provider import MockProvider

NOTE = negative_history_note("overruled")
MEADOWS_Q = "What did State v. Meadows hold about network control of a widget?"


def _evidence(question: str):
    return pack(rerank(retrieve(rewrite(question), get_corpus())))


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


# --- negative history: annotate, don't strip -------------------------------------

def test_overruled_case_cited_as_good_law_gets_the_note():
    result = run_pipeline(MEADOWS_Q, get_corpus(), MockProvider(cite_overruled=True))
    v = result.verification
    assert "State v. Meadows" in result.answer_text      # kept, not stripped
    assert NOTE in result.answer_text
    assert v.citations_stripped == 0
    meadows = [c for c in v.checks if "Meadows" in c.raw_citation or "12 Wn" in c.raw_citation]
    assert meadows and all(c.status_ok and c.status_annotated for c in meadows)
    assert any("note added" in f for f in v.flags)


def test_note_goes_after_the_parallel_cite():
    result = run_pipeline(MEADOWS_Q, get_corpus(), MockProvider(cite_overruled=True))
    assert f"State v. Meadows, 12 Wn. App. 2d 1 {NOTE}" in result.answer_text


def test_every_unqualified_sentence_gets_a_note():
    # MockProvider cites Meadows twice for this question, in two sentences.
    result = run_pipeline(MEADOWS_Q, get_corpus(), MockProvider(cite_overruled=True))
    assert result.answer_text.count(NOTE) == 2


def test_an_answer_that_states_the_status_gets_no_note():
    evidence = _evidence(MEADOWS_Q)
    text = ("State v. Meadows, 12 Wn. App. 2d 1, was overruled by State v. Northup, "
            "which now controls.")
    cleaned, v = verify(text, evidence)
    assert all(c.status_ok and not c.status_annotated for c in v.checks)
    assert NOTE not in cleaned


def test_audit_mode_detects_but_changes_nothing():
    evidence = _evidence("What is unlawful widget operation?")
    text = ("Under RCW 70.400.010, operation requires an endorsement. "
            "See State v. Fabricated, 404 Wn.2d 1 (2099).")
    audited, v = verify(text, evidence, mode="audit")
    assert audited == text
    assert v.citations_stripped == 0
    assert any(not c.resolved for c in v.checks)
    assert any("unresolved hallucinated citation" in f for f in v.flags)


# --- citation extraction ------------------------------------------------------------

def test_case_names_do_not_run_across_sentences_or_absorb_lead_words():
    text = ("Under the Widget Safety Act. State v. Northup. The court in Cascade Widget Co. "
            "v. Dep't of Licensing agreed. Under State v. Meadows, 12 Wn. App. 2d 1, no.")
    cites = extract_citations(text)
    assert "State v. Northup" in cites
    assert "State v. Meadows" in cites
    assert "Cascade Widget Co. v. Dep't" in cites
    assert not any(c.startswith(("Under", "Act", "The")) or c.endswith("The") for c in cites)
