"""LLM provider seam (Stage 5: Answer).

In the production system this is where a local Ollama model or the Claude API
generates the answer, constrained to an allowed-citations list. For a
dependency-free, deterministic demo we ship a MockProvider instead.

The point of the showcase is Stage 6 (Verify): no matter what the model emits —
including a hallucinated citation, or an overruled case cited as good law — the
verify gate catches it before the user sees the answer. The MockProvider can
misbehave on purpose so you can watch that happen.
"""

from __future__ import annotations

from typing import Protocol

from walegal_demo.types import EvidencePack


class LLMProvider(Protocol):
    """Interface a real provider (Ollama / Claude) would implement."""

    def generate(self, question: str, evidence: EvidencePack) -> str:
        """Produce an answer that cites only from `evidence.allowed_cites`."""
        ...

    def revise(self, question: str, evidence: EvidencePack, draft: str,
               feedback: list[str]) -> str:
        """Rewrite `draft` given the verifier's feedback (agent mode only)."""
        ...


FABRICATED = "State v. Fabricated, 404 Wn.2d 1 (2099)"


class MockProvider:
    """Deterministic stand-in for a real LLM.

    Composes a short answer that cites the top two authorities in the evidence
    pack. Switches make it misbehave the way real models do:

    * ``hallucinate``    — append a citation that is NOT in the evidence pack;
    * ``overstate``      — use definitive language with no hedging;
    * ``cite_overruled`` — cite a negative-history authority from the pack as
      if it were good law;
    * ``stubborn``       — (agent mode) keep the hallucinated citation when
      asked to revise, so the audit gate has to refuse the answer.

    ``revise`` fixes ungrounded citations but ignores negative-history warnings,
    which is what the production local model often did; agent mode's finalize
    step then adds the same note the pipeline adds.
    """

    def __init__(self, hallucinate: bool = False, overstate: bool = False,
                 cite_overruled: bool = False, stubborn: bool = False) -> None:
        self.hallucinate = hallucinate
        self.overstate = overstate
        self.cite_overruled = cite_overruled
        self.stubborn = stubborn

    def generate(self, question: str, evidence: EvidencePack) -> str:
        cites = [p.authority.canonical_cite for p in evidence.passages]
        if not cites:
            return "No authority was found in the corpus to answer this question."

        primary = cites[0]
        if self.overstate:
            # Definitive language with NO hedging — should trip the overstatement flag.
            sentences = [
                f"Under {primary}, the defendant will always prevail; this "
                f"guarantees dismissal."
            ]
        else:
            sentences = [
                f"Under {primary}, the conduct described is governed by the Widget "
                f"Safety Act."
            ]
            if len(cites) > 1:
                sentences.append(
                    f"Courts have generally held that this framework applies as "
                    f"stated in {cites[1]}."
                )
        if self.cite_overruled:
            bad = next((p.authority for p in evidence.passages
                        if p.authority.status != "good"), None)
            if bad is not None:
                cite = ", ".join(bad.all_cites)
                sentences.append(f"See also {cite}, which reached the same result.")
        if self.hallucinate:
            # A plausible-looking citation that is NOT in the evidence pack.
            sentences.append(f"The leading authority on this point is {FABRICATED}.")
        return " ".join(sentences)

    def revise(self, question: str, evidence: EvidencePack, draft: str,
               feedback: list[str]) -> str:
        if self.stubborn:
            return draft
        fixed = MockProvider(overstate=self.overstate, cite_overruled=self.cite_overruled)
        return fixed.generate(question, evidence)
