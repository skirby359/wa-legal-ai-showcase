"""Shared data types for the demo pipeline.

A sanitized subset of the types used by the private production system
(WA Legal AI). The shapes mirror the real pipeline so the architecture is
faithful, but nothing here touches the real corpus or system prompts.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# Authority types, mirroring the production enum.
AUTHORITY_CONSTITUTION = "constitution"
AUTHORITY_STATUTE = "statute"
AUTHORITY_CASE = "case"
AUTHORITY_REGULATION = "regulation"

# Court levels: lower number == higher authority.
COURT_SCOTUS = 0
COURT_STATE_SUPREME = 1
COURT_APPEALS = 2
COURT_TRIAL = 3
COURT_NONE = -1  # statutes / regulations / constitution


@dataclass(frozen=True)
class Authority:
    """One authority in the corpus (a statute section, case, etc.)."""

    authority_id: str
    canonical_cite: str
    authority_type: str
    text: str
    court_level: int = COURT_NONE
    status: str = "good"  # good | overruled | abrogated | superseded | repealed
    parallel_cites: tuple[str, ...] = ()

    @property
    def all_cites(self) -> tuple[str, ...]:
        """The canonical cite followed by any parallel reporter cites."""
        return (self.canonical_cite, *self.parallel_cites)


@dataclass
class Issue:
    """A single legal issue extracted from the user's question (Stage 1)."""

    description: str
    search_terms: list[str] = field(default_factory=list)


@dataclass
class RewriteResult:
    """Output of Stage 1: Rewrite."""

    original_query: str
    issues: list[Issue] = field(default_factory=list)
    is_legal: bool = True
    refusal_reason: str | None = None


@dataclass
class RetrievedPassage:
    """A scored passage retrieved from the corpus (Stages 2-3)."""

    authority: Authority
    bm25_score: float = 0.0
    boosted_score: float = 0.0


@dataclass
class EvidencePack:
    """Output of Stage 4: Pack — the allowed-citations context."""

    passages: list[RetrievedPassage]
    has_statute: bool = False

    @property
    def allowed_cites(self) -> set[str]:
        """The only citations an answer is permitted to use."""
        return {p.authority.canonical_cite for p in self.passages}


@dataclass
class CitationCheck:
    """Result of checking a single citation in an answer (Stage 6)."""

    raw_citation: str
    resolved: bool
    stripped: bool = False
    status_ok: bool = True
    reason: str = ""
    status: str = "good"           # the cited authority's status, when it resolved
    status_annotated: bool = False  # passed only because the negative-history note was added


@dataclass
class VerificationResult:
    """Output of Stage 6: Verify — the anti-hallucination gate."""

    passed: bool
    citations_checked: int = 0
    citations_passed: int = 0
    citations_stripped: int = 0
    flags: list[str] = field(default_factory=list)
    checks: list[CitationCheck] = field(default_factory=list)
    stripped_ratio: float = 0.0


@dataclass
class TraceStep:
    """One step of an agent run: a tool call, a model call, or an audit."""

    kind: str    # "tool" | "llm" | "audit" | "cap"
    name: str    # tool name, "draft"/"revise", "audit", or the cap that was hit
    detail: str = ""


@dataclass
class PipelineResult:
    """Final output of one question, from the pipeline or the agent.

    Both modes return this shape so the evaluation harness scores them with the
    same code.
    """

    answer_text: str          # post-verification (cleaned) answer
    rendered_text: str        # answer + disclaimer + build metadata
    raw_answer_text: str = ""  # pre-verification answer from the LLM
    evidence_pack: EvidencePack | None = None
    verification: VerificationResult | None = None
    rewrite: RewriteResult | None = None
    refused: bool = False
    refusal_reason: str = ""
    build_id: str = ""
    mode: str = "pipeline"    # "pipeline" | "agent"
    outcome: str = "answered"  # "answered" | "refused" | "could_not_verify"
    trace: list[TraceStep] = field(default_factory=list)
    tool_calls: int = 0
    llm_calls: int = 0
