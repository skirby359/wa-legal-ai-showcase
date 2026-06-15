"""The 7-stage query pipeline (sanitized demo).

    Question -> Rewrite -> Retrieve -> Rerank -> Pack -> Answer -> Verify -> Render

This mirrors the production architecture stage-for-stage. The retrieval here is
simple keyword overlap (the real system uses BM25 + dense vectors with
Reciprocal Rank Fusion and a cross-encoder reranker), and the LLM is mocked, but
Stage 6 (Verify) implements the same anti-hallucination idea: every citation in
the answer is checked against the evidence pack, and any citation not grounded
there is stripped before the user ever sees it.
"""

from __future__ import annotations

import re

from walegal_demo.provider import LLMProvider, MockProvider
from walegal_demo.types import (
    AUTHORITY_STATUTE,
    Authority,
    CitationCheck,
    EvidencePack,
    Issue,
    PipelineResult,
    RetrievedPassage,
    RewriteResult,
    VerificationResult,
)

BUILD_ID = "demo-2026.06"

_STOPWORDS = frozenset(
    "a an the is are was were be to of in for on with at by from as into "
    "and or but not what how when does do can could would should may i my "
    "it this that these those if then than so very just also only such under "
    "about who whom whose where which".split()
)

# --- Citation extraction patterns ---
_RCW = re.compile(r"RCW\s+\d+[A-Z]?\.\d+\.\d+(?:\(\d+\))*", re.I)
_CONST = re.compile(r"Const\.\s+art\.\s+[IVXLC]+,\s+§\s+\d+", re.I)
_REPORTER = re.compile(r"\d+\s+(?:Wn\.?\s?(?:App\.?\s?)?2d|P\.\s?\d?d|Wn\.2d)\s+\d+", re.I)
# Case name: "Word[ Word...] v. Word[ Word...]" possibly followed by reporter/year.
_CASE = re.compile(
    r"[A-Z][A-Za-z.'&]+(?:\s+[A-Z][A-Za-z.'&]+)*\s+v\.\s+"
    r"[A-Z][A-Za-z.'&]+(?:\s+[A-Z][A-Za-z.'&]+)*"
)
_RCW_SUBSECTION = re.compile(r"(\(\d+\))+$")


def _tokenize(text: str) -> list[str]:
    return [w for w in re.findall(r"[a-z]{3,}", text.lower()) if w not in _STOPWORDS]


def _normalize_case_name(name: str) -> str:
    name = re.sub(r",.*$", "", name)            # drop reporter/year tail
    name = re.sub(r"\s*\(.*?\)\s*$", "", name)  # drop trailing parenthetical
    name = re.sub(r"\s+", " ", name).strip().lower().replace(".", "").replace(",", "")
    return name


# ---------------------------------------------------------------- Stage 1
def rewrite(query: str) -> RewriteResult:
    """Decompose the question into searchable issues; flag obvious non-questions."""
    terms = _tokenize(query)
    if not terms:
        return RewriteResult(
            original_query=query,
            is_legal=False,
            refusal_reason="The question does not contain a searchable legal issue.",
        )
    issue = Issue(description=query.strip(), search_terms=terms)
    return RewriteResult(original_query=query, issues=[issue])


# ---------------------------------------------------------------- Stage 2
def retrieve(rewrite_result: RewriteResult, corpus: list[Authority]) -> list[RetrievedPassage]:
    """Score every authority by keyword overlap with the issue terms."""
    terms: set[str] = set()
    for issue in rewrite_result.issues:
        terms.update(issue.search_terms)

    passages: list[RetrievedPassage] = []
    for auth in corpus:
        auth_tokens = set(_tokenize(auth.text + " " + auth.canonical_cite))
        overlap = len(terms & auth_tokens)
        if overlap > 0:
            passages.append(RetrievedPassage(authority=auth, bm25_score=float(overlap)))
    passages.sort(key=lambda p: p.bm25_score, reverse=True)
    return passages


# ---------------------------------------------------------------- Stage 3
def rerank(passages: list[RetrievedPassage]) -> list[RetrievedPassage]:
    """Boost by court hierarchy: statutes and higher courts rank up."""
    for p in passages:
        boost = 0.0
        if p.authority.authority_type == AUTHORITY_STATUTE:
            boost = 1.5  # statutes are primary authority
        elif p.authority.court_level >= 0:
            boost = max(0.0, (3 - p.authority.court_level)) * 0.75
        # Down-rank authorities with negative treatment.
        if p.authority.status != "good":
            boost -= 2.0
        p.boosted_score = p.bm25_score + boost
    passages.sort(key=lambda p: p.boosted_score, reverse=True)
    return passages


# ---------------------------------------------------------------- Stage 4
def pack(passages: list[RetrievedPassage], top_k: int = 4) -> EvidencePack:
    """Assemble the top passages into the allowed-citations context."""
    chosen = passages[:top_k]
    has_statute = any(p.authority.authority_type == AUTHORITY_STATUTE for p in chosen)
    return EvidencePack(passages=chosen, has_statute=has_statute)


# ---------------------------------------------------------------- Stage 5
def answer(question: str, evidence: EvidencePack, provider: LLMProvider) -> str:
    """Generate an answer constrained to the evidence pack's allowed citations."""
    return provider.generate(question, evidence)


# ---------------------------------------------------------------- Stage 6
def _extract_citations(text: str) -> list[str]:
    """Pull every citation-looking span out of the answer text."""
    found: list[str] = []
    seen: set[str] = set()
    for pat in (_RCW, _CONST, _REPORTER, _CASE):
        for m in pat.finditer(text):
            cite = m.group(0).strip().rstrip(".,")
            key = cite.lower()
            if key not in seen:
                seen.add(key)
                found.append(cite)
    return found


def _resolves_in_evidence(cite: str, evidence: EvidencePack) -> bool:
    """Does this citation ground to an authority in the evidence pack?"""
    allowed = evidence.allowed_cites
    # 1. Exact statute / constitution match (after stripping subsections).
    base = _RCW_SUBSECTION.sub("", cite).strip()
    if cite in allowed or base in allowed:
        return True
    # 2. Reporter parallel-cite match.
    cite_clean = cite.lower().replace(" ", "")
    for p in evidence.passages:
        for pc in p.authority.parallel_cites:
            if pc.lower().replace(" ", "") == cite_clean:
                return True
    # 3. Fuzzy case-name match against canonical cites.
    norm = _normalize_case_name(cite)
    if norm:
        for p in evidence.passages:
            ev = _normalize_case_name(p.authority.canonical_cite)
            if ev and (norm == ev or ev.startswith(norm) or norm.startswith(ev)):
                return True
    return False


# Overstatement detection (Check 3 in production).
_DEFINITIVE = [
    re.compile(r"\b(?:always|never|guarantees?|will\s+(?:always|prevail))\b", re.I),
]
_HEDGE = [re.compile(r"\b(?:generally|typically|may|likely|courts?\s+have)\b", re.I)]


def verify(answer_text: str, evidence: EvidencePack) -> tuple[str, VerificationResult]:
    """Stage 6: strip any citation not grounded in the evidence pack.

    Returns the cleaned answer text plus a VerificationResult. Mirrors the
    production verify gate (existence + negative-treatment + overstatement
    checks); the production system additionally checks pin-cites, hierarchy,
    and semantic claim support.
    """
    citations = _extract_citations(answer_text)
    checks: list[CitationCheck] = []
    flags: list[str] = []
    stripped_cites: set[str] = set()

    # Map canonical cite -> authority for status checks.
    by_cite = {p.authority.canonical_cite: p.authority for p in evidence.passages}

    for cite in citations:
        if _resolves_in_evidence(cite, evidence):
            auth = _match_authority(cite, by_cite, evidence)
            status_ok = True
            reason = ""
            if auth and auth.status != "good" and auth.status not in answer_text.lower():
                # Authority is overruled/repealed and not noted: strip it.
                status_ok = False
                reason = f"authority is {auth.status}; not noted in answer"
                stripped_cites.add(cite)
                flags.append(f"negative treatment: {cite} is {auth.status}")
            checks.append(
                CitationCheck(raw_citation=cite, resolved=True,
                              stripped=not status_ok, status_ok=status_ok, reason=reason)
            )
        else:
            # Ungrounded (hallucinated) citation -> strip the sentence containing it.
            stripped_cites.add(cite)
            checks.append(
                CitationCheck(raw_citation=cite, resolved=False, stripped=True,
                              reason="citation does not resolve in corpus (hallucinated)")
            )
            flags.append(f"stripped hallucinated citation: {cite}")

    cleaned = _drop_sentences_with(answer_text, citations, stripped_cites)

    # Overstatement check.
    has_def = any(p.search(cleaned) for p in _DEFINITIVE)
    has_hedge = any(p.search(cleaned) for p in _HEDGE)
    if has_def and not has_hedge:
        flags.append("overstatement: definitive language without hedging")

    total = len(checks)
    stripped = sum(1 for c in checks if c.stripped)
    passed_n = sum(1 for c in checks if c.resolved and not c.stripped)
    ratio = stripped / total if total else 0.0
    result = VerificationResult(
        passed=ratio <= 0.34,  # production uses a configurable max_stripped_ratio
        citations_checked=total,
        citations_passed=passed_n,
        citations_stripped=stripped,
        flags=flags,
        checks=checks,
        stripped_ratio=ratio,
    )
    return _tidy(cleaned), result


def _match_authority(cite, by_cite, evidence):
    base = _RCW_SUBSECTION.sub("", cite).strip()
    if cite in by_cite:
        return by_cite[cite]
    if base in by_cite:
        return by_cite[base]
    norm = _normalize_case_name(cite)
    for p in evidence.passages:
        if _normalize_case_name(p.authority.canonical_cite) == norm:
            return p.authority
    return None


def _drop_sentences_with(text: str, citations: list[str], to_strip: set[str]) -> str:
    """Drop every sentence that contains a to-be-stripped citation.

    Citations are masked to period-free placeholders before sentence splitting,
    so internal periods ("State v.", "Wn.2d") can't be mistaken for sentence
    boundaries — the bug a naive split would hit.
    """
    if not to_strip:
        return _tidy(text)

    masked = text
    placeholders: dict[str, str] = {}
    # Longest first so a short cite isn't masked inside a longer one.
    for i, cite in enumerate(sorted(citations, key=len, reverse=True)):
        ph = f"\x00C{i}\x00"
        masked = masked.replace(cite, ph)
        placeholders[ph] = cite

    kept: list[str] = []
    for sentence in re.split(r"(?<=\.)\s+", masked):
        drops = any(ph in sentence and placeholders[ph] in to_strip for ph in placeholders)
        if not drops:
            kept.append(sentence)
    out = " ".join(kept)
    for ph, cite in placeholders.items():  # restore surviving citations
        out = out.replace(ph, cite)
    return _tidy(out)


def _tidy(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


# ---------------------------------------------------------------- Stage 7
def render(answer_text: str, verification: VerificationResult, build_id: str) -> str:
    """Format the final answer with a scope disclaimer and build metadata."""
    body = answer_text if answer_text else "(No grounded answer could be produced.)"
    disclaimer = (
        "\n\n---\nThis is automated legal information, not legal advice, and may be "
        "incomplete. Verify every citation against the official source. "
        f"[build {build_id}]"
    )
    return body + disclaimer


# ---------------------------------------------------------------- Orchestrator
def run_pipeline(
    query: str,
    corpus: list[Authority],
    provider: LLMProvider | None = None,
) -> PipelineResult:
    """Run the full 7-stage pipeline for one question."""
    provider = provider or MockProvider()

    rw = rewrite(query)
    if not rw.is_legal:
        return PipelineResult(
            answer_text="", rendered_text=rw.refusal_reason or "Refused.",
            rewrite=rw, refused=True, refusal_reason=rw.refusal_reason or "", build_id=BUILD_ID,
        )

    retrieved = retrieve(rw, corpus)
    if not retrieved:
        reason = "No authority in the corpus addresses this question (out of scope)."
        return PipelineResult(
            answer_text="", rendered_text=reason, rewrite=rw,
            refused=True, refusal_reason=reason, build_id=BUILD_ID,
        )

    reranked = rerank(retrieved)
    evidence = pack(reranked)
    raw = answer(query, evidence, provider)
    cleaned, verification = verify(raw, evidence)
    rendered = render(cleaned, verification, BUILD_ID)

    return PipelineResult(
        answer_text=cleaned,
        rendered_text=rendered,
        raw_answer_text=raw,
        evidence_pack=evidence,
        verification=verification,
        rewrite=rw,
        build_id=BUILD_ID,
    )
