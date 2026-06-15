"""LLM provider seam (Stage 5: Answer).

In the production system this is where a local Ollama model or the Claude API
generates the answer, constrained to an allowed-citations list. For a
dependency-free, deterministic demo we ship a MockProvider instead.

The point of the showcase is Stage 6 (Verify): no matter what the model emits —
including a hallucinated citation — the verify gate strips anything not grounded
in the evidence pack. The MockProvider can deliberately hallucinate so you can
watch that happen.
"""

from __future__ import annotations

from typing import Protocol

from walegal_demo.types import EvidencePack


class LLMProvider(Protocol):
    """Interface a real provider (Ollama / Claude) would implement."""

    def generate(self, question: str, evidence: EvidencePack) -> str:
        """Produce an answer that cites only from `evidence.allowed_cites`."""
        ...


class MockProvider:
    """Deterministic stand-in for a real LLM.

    Composes a short answer that cites the top statute and case in the evidence
    pack. With `hallucinate=True` it appends a citation that is NOT in the
    evidence pack, to demonstrate the verify stage stripping it.
    """

    def __init__(self, hallucinate: bool = False, overstate: bool = False) -> None:
        self.hallucinate = hallucinate
        self.overstate = overstate

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
        if self.hallucinate:
            # A plausible-looking citation that is NOT in the evidence pack.
            sentences.append(
                "The leading authority on this point is State v. Fabricated, "
                "404 Wn.2d 1 (2099)."
            )
        return " ".join(sentences)
