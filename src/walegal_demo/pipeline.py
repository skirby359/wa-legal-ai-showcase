"""The 7-stage query pipeline (sanitized demo).

    Question -> Rewrite -> Retrieve -> Rerank -> Pack -> Answer -> Verify -> Render

This mirrors the production architecture stage-for-stage. The retrieval here is
simple keyword overlap (the real system uses BM25 + dense vectors with
Reciprocal Rank Fusion and a cross-encoder reranker), and the LLM is mocked, but
Stage 6 (Verify) implements the same ideas as production:

* every citation in the answer is checked against the evidence pack, and any
  citation not grounded there is stripped before the user ever sees it;
* a citation to overruled, abrogated, superseded or repealed authority that the
  answer presents as good law is kept, and a negative-history note is inserted
  right after it.

The same verifier, note and renderer are reused by agent mode (`agent.py`).
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

BUILD_ID = "demo-2026.11"

# Production uses a configurable max_stripped_ratio.
MAX_UNRESOLVED_RATIO = 0.34

NEGATIVE_STATUSES = ("overruled", "abrogated", "superseded", "repealed")

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
# Capitalised words that start a sentence but are not part of a party name
# ("Under State v. Northup" cites State v. Northup).
_LEADING_NON_PARTY = re.compile(
    r"^(?:(?:Under|In|See|The|As|Per|Accord|Cf|But|Also|And|Compare|Following)\s+)+"
)
_RCW_SUBSECTION = re.compile(r"(\(\d+\))+$")
# What may follow a case name and still belong to the citation: parallel
# reporter cites and a year. The negative-history note goes after all of it.
_CITE_TAIL = re.compile(r"(?:,\s*" + _REPORTER.pattern + r")*(?:\s*\(\d{4}\))?", re.I)


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
def keyword_score(terms: set[str], auth: Authority) -> float:
    """Keyword overlap between the search terms and one authority."""
    return float(len(terms & set(_tokenize(auth.text + " " + auth.canonical_cite))))


def retrieve(rewrite_result: RewriteResult, corpus: list[Authority]) -> list[RetrievedPassage]:
    """Score every authority by keyword overlap with the issue terms."""
    terms: set[str] = set()
    for issue in rewrite_result.issues:
        terms.update(issue.search_terms)

    passages: list[RetrievedPassage] = []
    for auth in corpus:
        overlap = keyword_score(terms, auth)
        if overlap > 0:
            passages.append(RetrievedPassage(authority=auth, bm25_score=overlap))
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
PACK_TOP_K = 4


def pack(passages: list[RetrievedPassage], top_k: int = PACK_TOP_K) -> EvidencePack:
    """Assemble the top passages into the allowed-citations context."""
    chosen = passages[:top_k]
    has_statute = any(p.authority.authority_type == AUTHORITY_STATUTE for p in chosen)
    return EvidencePack(passages=chosen, has_statute=has_statute)


# ---------------------------------------------------------------- Stage 5
def answer(question: str, evidence: EvidencePack, provider: LLMProvider) -> str:
    """Generate an answer constrained to the evidence pack's allowed citations."""
    return provider.generate(question, evidence)


# ---------------------------------------------------------------- Stage 6
def extract_citations(text: str) -> list[str]:
    """Pull every citation-looking span out of the answer text."""
    found: list[str] = []
    seen: set[str] = set()
    for pat in (_RCW, _CONST, _REPORTER, _CASE):
        for m in pat.finditer(text):
            cite = m.group(0).strip().rstrip(".,")
            if pat is _CASE:
                cite = _trim_case_match(cite)
                if cite is None:
                    continue
            key = cite.lower()
            if key not in seen:
                seen.add(key)
                found.append(cite)
    return sorted(found, key=text.find)  # reading order


def _trim_case_match(span: str) -> str | None:
    """Cut a case-name match back to the citation itself.

    The case pattern allows periods inside names ("Co.", "Dep't"), so a match
    can run across a sentence break: "Safety Act. State v. Northup. The ...".
    Keep the last sentence of the first party and the first of the second,
    then drop leading words such as "Under" or "See".
    """
    head, sep, tail = span.partition(" v. ")
    if not sep:
        return None
    head = re.split(r"\.\s+(?=[A-Z])", head)[-1]
    tail = re.split(r"\.\s+", tail, maxsplit=1)[0]
    head = _LEADING_NON_PARTY.sub("", head)
    if not head or not tail:
        return None
    return f"{head} v. {tail}".rstrip(".,")


def match_authority(cite: str, evidence: EvidencePack) -> Authority | None:
    """The evidence-pack authority this citation refers to, or None if it is ungrounded."""
    base = _RCW_SUBSECTION.sub("", cite).strip()
    cite_clean = cite.lower().replace(" ", "")
    # 1. Exact statute / constitution / case-name match (after stripping subsections).
    for p in evidence.passages:
        if p.authority.canonical_cite in (cite, base):
            return p.authority
    # 2. Reporter parallel-cite match.
    for p in evidence.passages:
        if any(pc.lower().replace(" ", "") == cite_clean for pc in p.authority.parallel_cites):
            return p.authority
    # 3. Fuzzy case-name match against canonical cites.
    norm = _normalize_case_name(cite)
    if norm:
        for p in evidence.passages:
            ev = _normalize_case_name(p.authority.canonical_cite)
            if ev and (norm == ev or ev.startswith(norm) or norm.startswith(ev)):
                return p.authority
    return None


def ungrounded_citations(text: str, evidence: EvidencePack | None) -> list[str]:
    """Citations in `text` that do not resolve to the evidence pack (used to score M1)."""
    if evidence is None:
        return extract_citations(text)
    return [c for c in extract_citations(text) if match_authority(c, evidence) is None]


def _sentences(text: str, citations: list[str]) -> list[tuple[str, set[str]]]:
    """Split `text` into sentences, each with the citations it contains.

    Citations are masked to period-free placeholders before sentence splitting,
    so internal periods ("State v.", "Wn.2d", "art.") can't be mistaken for
    sentence boundaries — the bug a naive split would hit.
    """
    masked = text
    placeholders: dict[str, str] = {}
    # Longest first so a short cite isn't masked inside a longer one.
    for i, cite in enumerate(sorted(citations, key=len, reverse=True)):
        ph = f"\x00C{i}\x00"
        masked = masked.replace(cite, ph)
        placeholders[ph] = cite

    out: list[tuple[str, set[str]]] = []
    for sentence in re.split(r"(?<=\.)\s+", masked):
        cites = {cite for ph, cite in placeholders.items() if ph in sentence}
        for ph, cite in placeholders.items():  # restore the citations
            sentence = sentence.replace(ph, cite)
        out.append((sentence, cites))
    return out


def _status_noted(cite: str, status: str, sentences: list[tuple[str, set[str]]]) -> bool:
    """Does every sentence that cites `cite` also say the authority is `status`?"""
    return all(status in sent.lower() for sent, cites in sentences if cite in cites)


# Overstatement detection (Check 3 in production).
_DEFINITIVE = [
    re.compile(r"\b(?:always|never|guarantees?|will\s+(?:always|prevail))\b", re.I),
]
_HEDGE = [re.compile(r"\b(?:generally|typically|may|likely|courts?\s+have)\b", re.I)]


def verify(
    answer_text: str, evidence: EvidencePack, mode: str = "full"
) -> tuple[str, VerificationResult]:
    """Stage 6: check every citation in the answer against the evidence pack.

    Modes, as in production:

    * ``full``  — detect, then strip every sentence that carries an ungrounded
      (hallucinated) citation. The pipeline uses this.
    * ``audit`` — detect only; the text is returned unchanged. Agent mode audits
      its draft this way and sends failures back to the model for one revision.

    A citation to negative-history authority that the answer does not qualify is
    flagged here but not stripped; :func:`annotate_negative_history` adds the
    note afterwards. The production verifier also checks pin-cites, court
    hierarchy and semantic claim support.
    """
    if mode not in ("full", "audit"):
        raise ValueError(f"unknown verify mode: {mode!r}")
    citations = extract_citations(answer_text)
    sentences = _sentences(answer_text, citations)
    checks: list[CitationCheck] = []
    flags: list[str] = []

    for cite in citations:
        auth = match_authority(cite, evidence)
        if auth is not None:
            status = auth.status
            ok = status == "good" or _status_noted(cite, status, sentences)
            reason = "" if ok else f"authority is {status}; the answer does not say so"
            checks.append(CitationCheck(raw_citation=cite, resolved=True, status_ok=ok,
                                        status=status, reason=reason))
            if not ok:
                flags.append(f"negative history: {cite} is {status}; the answer does not say so")
        else:
            strip = mode == "full"
            checks.append(CitationCheck(
                raw_citation=cite, resolved=False, stripped=strip,
                reason="citation does not resolve in the evidence (hallucinated)",
            ))
            verb = "stripped" if strip else "unresolved"
            flags.append(f"{verb} hallucinated citation: {cite}")

    text = answer_text
    if mode == "full":
        to_strip = {c.raw_citation for c in checks if c.stripped}
        text = _drop_sentences_with(answer_text, citations, to_strip)

    # Overstatement check.
    has_def = any(p.search(text) for p in _DEFINITIVE)
    has_hedge = any(p.search(text) for p in _HEDGE)
    if has_def and not has_hedge:
        flags.append("overstatement: definitive language without hedging")

    total = len(checks)
    unresolved = sum(1 for c in checks if not c.resolved)
    ratio = unresolved / total if total else 0.0
    result = VerificationResult(
        passed=ratio <= MAX_UNRESOLVED_RATIO,
        citations_checked=total,
        citations_passed=_count_passed(checks),
        citations_stripped=sum(1 for c in checks if c.stripped),
        flags=flags,
        checks=checks,
        stripped_ratio=ratio,
    )
    return _tidy(text), result


def _count_passed(checks: list[CitationCheck]) -> int:
    return sum(1 for c in checks if c.resolved and not c.stripped and c.status_ok)


def negative_history_note(status: str) -> str:
    """The note inserted after an unqualified negative-history citation.

    Same wording as production. The status comes from a machine-derived citation
    graph, hence "verify" rather than a definitive statement.
    """
    return f"[negative history: {status.upper()} — verify before relying on this authority]"


def annotate_negative_history(
    answer_text: str, verification: VerificationResult, evidence: EvidencePack
) -> str:
    """Qualify every negative-history citation the answer presents as good law.

    Runs after Verify. In every sentence that cites such an authority without
    saying so, the note is inserted right after the citation (after any parallel
    cites and year; one note covers a case's parallel cites). The status check
    is then re-run on the new text so the counts reflect what the reader sees.
    Checks that passed only because of the note are marked ``status_annotated``,
    so reports still count how often the model itself left the status out.

    Why annotate instead of strip: the status is machine-derived, and a case
    "overruled on other grounds" is still good law for other points. The reader
    gets the authority and the warning.
    """
    failing = [c for c in verification.checks
               if c.resolved and not c.status_ok and c.status in NEGATIVE_STATUSES]
    if not failing:
        return answer_text

    by_authority: dict[str, tuple[Authority, set[str]]] = {}
    for c in failing:
        auth = match_authority(c.raw_citation, evidence)
        if auth is not None:
            by_authority.setdefault(auth.authority_id, (auth, set()))[1].add(c.raw_citation)

    out: list[str] = []
    for sent, cites in _sentences(answer_text, extract_citations(answer_text)):
        for auth, auth_cites in by_authority.values():
            here = [c for c in cites if c in auth_cites]
            if not here or auth.status in sent.lower():
                continue
            pos, cite = min((sent.find(c), c) for c in here)
            end = _CITE_TAIL.match(sent, pos + len(cite)).end()
            sent = f"{sent[:end]} {negative_history_note(auth.status)}{sent[end:]}"
            verification.flags.append(
                f"negative history note added: {auth.canonical_cite} ({auth.status})"
            )
        out.append(sent)
    text = _tidy(" ".join(out))

    sentences = _sentences(text, extract_citations(text))
    for c in failing:
        if _status_noted(c.raw_citation, c.status, sentences):
            c.status_ok = True
            c.status_annotated = True
            c.reason = f"authority is {c.status}; negative-history note added"
    verification.citations_passed = _count_passed(verification.checks)
    return text


def _drop_sentences_with(text: str, citations: list[str], to_strip: set[str]) -> str:
    """Drop every sentence that contains a to-be-stripped citation."""
    if not to_strip:
        return _tidy(text)
    kept = [sent for sent, cites in _sentences(text, citations) if not cites & to_strip]
    return _tidy(" ".join(kept))


def _tidy(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


# ---------------------------------------------------------------- Stage 7
def render(answer_text: str, verification: VerificationResult | None, build_id: str) -> str:
    """Format the final answer with a scope disclaimer and build metadata."""
    body = answer_text if answer_text else "(No grounded answer could be produced.)"
    disclaimer = (
        "\n\n---\nThis is automated legal information, not legal advice, and may be "
        "incomplete. Verify every citation against the official source. "
        f"[build {build_id}]"
    )
    return body + disclaimer


# ---------------------------------------------------------------- Orchestrator
OUT_OF_SCOPE = "No authority in the corpus addresses this question (out of scope)."


def refused(rw: RewriteResult, reason: str, mode: str = "pipeline") -> PipelineResult:
    """A refusal result (shared by the pipeline and agent mode)."""
    return PipelineResult(
        answer_text="", rendered_text=reason, rewrite=rw, refused=True,
        refusal_reason=reason, build_id=BUILD_ID, mode=mode, outcome="refused",
    )


def run_pipeline(
    query: str,
    corpus: list[Authority],
    provider: LLMProvider | None = None,
) -> PipelineResult:
    """Run the full 7-stage pipeline for one question."""
    provider = provider or MockProvider()

    rw = rewrite(query)
    if not rw.is_legal:
        return refused(rw, rw.refusal_reason or "Refused.")

    retrieved = retrieve(rw, corpus)
    if not retrieved:
        return refused(rw, OUT_OF_SCOPE)

    reranked = rerank(retrieved)
    evidence = pack(reranked)
    raw = answer(query, evidence, provider)
    cleaned, verification = verify(raw, evidence, mode="full")
    cleaned = annotate_negative_history(cleaned, verification, evidence)
    rendered = render(cleaned, verification, BUILD_ID)

    return PipelineResult(
        answer_text=cleaned,
        rendered_text=rendered,
        raw_answer_text=raw,
        evidence_pack=evidence,
        verification=verification,
        rewrite=rw,
        build_id=BUILD_ID,
        llm_calls=1,
    )
