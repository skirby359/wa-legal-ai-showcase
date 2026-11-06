"""Agent mode (sanitized demo): a tool-using research loop, A/B-tested against the pipeline.

    plan ──► tools ──► plan …
      └──► draft ──► audit ──► finalize
                       └──► revise ──► audit

Production runs this as a LangGraph state graph talking to a local MCP stdio
server with four tools: ``search_authorities``, ``read_authority``,
``follow_citation`` and ``audit_citations`` (which wraps the pipeline's own
verifier). It works with any chat model: local Ollama, Claude or OpenAI. This
demo keeps the same shape in the standard library. The four tools are plain
functions over the corpus, and a scripted planner stands in for the model's
tool choices.

Only two things differ from the pipeline, by design, so an A/B measures them and
nothing else:

1. **How evidence is gathered.** The planner searches, reads what it found and
   follows the citation graph one hop, instead of one retrieval pass.
2. **An audit-and-revise loop before anything is returned.** The draft is
   verified in ``audit`` mode. Ungrounded citations and unqualified negative
   history go back to the model for one revision. If an ungrounded citation
   survives the revision, the answer is replaced by a "could not verify"
   message that names it, where the pipeline would strip it and answer anyway.

Everything else is shared with the pipeline: the refusal rules, the answer
provider, the pack size and hierarchy ordering, the verifier, the
negative-history note and the renderer.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from walegal_demo import pipeline as pl
from walegal_demo.provider import LLMProvider, MockProvider
from walegal_demo.types import (
    Authority,
    EvidencePack,
    PipelineResult,
    RetrievedPassage,
    TraceStep,
    VerificationResult,
)


@dataclass(frozen=True)
class AgentConfig:
    """Hard caps per question. Hitting a tool cap forces the draft from what exists."""

    max_tool_calls: int = 10
    max_revisions: int = 1
    search_limit: int = 3
    pack_top_k: int = pl.PACK_TOP_K  # the pipeline's own limit, so the arms compare fairly


# ---------------------------------------------------------------- tools
class CorpusTools:
    """The agent's four tools as pure functions over the corpus.

    Production serves these from an MCP server; the tools are stateless and the
    evidence ledger lives in the agent's state.
    """

    def __init__(self, corpus: list[Authority]) -> None:
        self.corpus = corpus
        self._everything = EvidencePack(passages=[RetrievedPassage(a) for a in corpus])
        # Citation graph: an edge for every citation in an authority's text that
        # resolves to another authority in the corpus.
        self._cites: dict[str, list[str]] = {}
        self._cited_by: dict[str, list[str]] = {a.canonical_cite: [] for a in corpus}
        for a in corpus:
            out: list[str] = []
            for raw in pl.extract_citations(a.text):
                target = pl.match_authority(raw, self._everything)
                if target and target.canonical_cite != a.canonical_cite \
                        and target.canonical_cite not in out:
                    out.append(target.canonical_cite)
                    self._cited_by[target.canonical_cite].append(a.canonical_cite)
            self._cites[a.canonical_cite] = out

    def search_authorities(self, query: str, limit: int = 3) -> list[str]:
        """Keyword search; returns the best-matching citations."""
        rw = pl.rewrite(query)
        terms = {t for issue in rw.issues for t in issue.search_terms}
        scored = [(pl.keyword_score(terms, a), a.canonical_cite) for a in self.corpus]
        hits = sorted((s for s in scored if s[0] > 0), key=lambda s: -s[0])
        return [cite for _score, cite in hits[:limit]]

    def read_authority(self, cite: str) -> Authority | None:
        """The full authority for a citation, or None if it does not resolve."""
        return pl.match_authority(cite, self._everything)

    def follow_citation(self, cite: str) -> tuple[list[str], list[str]]:
        """What this authority cites, and what cites it."""
        return list(self._cites.get(cite, [])), list(self._cited_by.get(cite, []))

    def audit_citations(self, draft: str, evidence: EvidencePack) -> VerificationResult:
        """The pipeline's verifier in audit mode: detect only, change nothing."""
        return pl.verify(draft, evidence, mode="audit")[1]


# ---------------------------------------------------------------- state + planner
@dataclass
class AgentState:
    question: str
    searched: bool = False
    search_hits: list[str] = field(default_factory=list)
    follow_hits: list[str] = field(default_factory=list)
    followed: set[str] = field(default_factory=set)
    ledger: dict[str, Authority] = field(default_factory=dict)  # what the agent has read
    trace: list[TraceStep] = field(default_factory=list)
    tool_calls: int = 0
    llm_calls: int = 0


class ScriptedPlanner:
    """Stands in for the model's tool choices.

    Search once, read the hits, follow each hit's citations one hop, read what
    that turns up, then draft. A real planner decides this turn by turn, and
    that is where a small local model goes wrong: it restricts its searches,
    rarely follows citations, or answers from memory.
    """

    def next_action(self, state: AgentState) -> tuple[str, str] | None:
        if not state.searched:
            return "search_authorities", state.question
        for cite in state.search_hits:
            if cite not in state.ledger:
                return "read_authority", cite
        for cite in state.search_hits:
            if cite not in state.followed:
                return "follow_citation", cite
        for cite in state.follow_hits:
            if cite not in state.ledger:
                return "read_authority", cite
        return None


def _run_tool(tools: CorpusTools, state: AgentState, name: str, arg: str,
              cfg: AgentConfig) -> None:
    state.tool_calls += 1
    if name == "search_authorities":
        state.searched = True
        state.search_hits = tools.search_authorities(arg, cfg.search_limit)
        detail = f"{len(state.search_hits)} hits: {', '.join(state.search_hits) or '-'}"
    elif name == "read_authority":
        auth = tools.read_authority(arg)
        if auth is None:
            detail = "not found"
        else:
            state.ledger[auth.canonical_cite] = auth
            status = "good law" if auth.status == "good" else auth.status.upper()
            detail = f"{auth.authority_type}, {status}"
    elif name == "follow_citation":
        state.followed.add(arg)
        cites, cited_by = tools.follow_citation(arg)
        for c in cites + cited_by:
            if c not in state.follow_hits:
                state.follow_hits.append(c)
        detail = f"cites {', '.join(cites) or '-'}; cited by {', '.join(cited_by) or '-'}"
    else:  # pragma: no cover - the planner only emits the three names above
        raise ValueError(name)
    state.trace.append(TraceStep("tool", f"{name}({arg})", detail))


def select_pack(state: AgentState, cfg: AgentConfig) -> EvidencePack:
    """Choose the evidence pack from the ledger with the pipeline's own rules.

    The pack is selected by code, not by the model: the same keyword score, the
    same hierarchy rerank and the same size limit as the pipeline's Stage 4.
    """
    rw = pl.rewrite(state.question)
    terms = {t for issue in rw.issues for t in issue.search_terms}
    passages = [RetrievedPassage(a, bm25_score=pl.keyword_score(terms, a))
                for a in state.ledger.values()]
    return pl.pack(pl.rerank(passages), top_k=cfg.pack_top_k)


def _audit_summary(report: VerificationResult) -> str:
    unresolved = [c.raw_citation for c in report.checks if not c.resolved]
    status = [c.raw_citation for c in report.checks if c.resolved and not c.status_ok]
    parts = [f"{report.citations_checked} citations"]
    parts.append(f"{len(unresolved)} unresolved" + (f" ({', '.join(unresolved)})" if unresolved else ""))
    parts.append(f"{len(status)} negative-history warnings")
    return ", ".join(parts)


def _needs_revision(report: VerificationResult) -> bool:
    return any(not c.resolved or not c.status_ok for c in report.checks)


# ---------------------------------------------------------------- orchestrator
def run_agent(
    query: str,
    corpus: list[Authority],
    provider: LLMProvider | None = None,
    cfg: AgentConfig | None = None,
) -> PipelineResult:
    """Answer one question in agent mode."""
    provider = provider or MockProvider()
    cfg = cfg or AgentConfig()

    # The pipeline's deterministic refusal rules run first, in code.
    rw = pl.rewrite(query)
    if not rw.is_legal:
        return pl.refused(rw, rw.refusal_reason or "Refused.", mode="agent")

    tools = CorpusTools(corpus)
    planner = ScriptedPlanner()
    state = AgentState(question=query)

    # plan -> tools -> plan ...
    while (action := planner.next_action(state)) is not None:
        if state.tool_calls >= cfg.max_tool_calls:
            state.trace.append(TraceStep("cap", "max_tool_calls",
                                         f"{cfg.max_tool_calls} calls; drafting from what was read"))
            break
        _run_tool(tools, state, *action, cfg)

    def finish(result: PipelineResult) -> PipelineResult:
        result.trace, result.tool_calls, result.llm_calls = state.trace, state.tool_calls, state.llm_calls
        return result

    if not state.ledger:
        return finish(pl.refused(rw, pl.OUT_OF_SCOPE, mode="agent"))

    evidence = select_pack(state, cfg)

    # draft -> audit
    draft = provider.generate(query, evidence)
    raw = draft
    state.llm_calls += 1
    state.trace.append(TraceStep("llm", "draft", f"pack of {len(evidence.passages)}"))
    report = tools.audit_citations(draft, evidence)
    state.trace.append(TraceStep("audit", "audit_citations", _audit_summary(report)))

    # -> revise -> audit (at most cfg.max_revisions times)
    revisions = 0
    while _needs_revision(report) and revisions < cfg.max_revisions:
        draft = provider.revise(query, evidence, draft, list(report.flags))
        revisions += 1
        state.llm_calls += 1
        state.trace.append(TraceStep("llm", "revise", f"{len(report.flags)} audit findings sent back"))
        report = tools.audit_citations(draft, evidence)
        state.trace.append(TraceStep("audit", "audit_citations", _audit_summary(report)))

    # finalize
    unresolved = [c.raw_citation for c in report.checks if not c.resolved]
    if unresolved:
        reason = (f"Could not verify this answer: {len(unresolved)} citation(s) did not resolve "
                  f"to the evidence gathered ({', '.join(unresolved)}).")
        return finish(PipelineResult(
            answer_text="", rendered_text=reason, raw_answer_text=raw,
            evidence_pack=evidence, verification=report, rewrite=rw, refused=True,
            refusal_reason=reason, build_id=pl.BUILD_ID, mode="agent",
            outcome="could_not_verify",
        ))

    text = pl.annotate_negative_history(" ".join(draft.split()), report, evidence)
    return finish(PipelineResult(
        answer_text=text,
        rendered_text=pl.render(text, report, pl.BUILD_ID),
        raw_answer_text=raw,
        evidence_pack=evidence,
        verification=report,
        rewrite=rw,
        build_id=pl.BUILD_ID,
        mode="agent",
    ))
