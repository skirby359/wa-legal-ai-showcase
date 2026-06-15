# Architecture

This document maps the showcase to the production system stage-by-stage. The
shapes and control flow are faithful; the data and models are sanitized.

## The 7-stage pipeline

```
Question → Rewrite → Retrieve → Rerank → Pack → Answer → Verify → Render
```

| # | Stage | Showcase (`pipeline.py`) | Production |
|---|-------|--------------------------|------------|
| 1 | **Rewrite** | Tokenize into search terms; refuse content-free input | LLM decomposes the question into legal issues; refuses out-of-scope |
| 2 | **Retrieve** | Keyword overlap against the corpus | BM25 + dense vector search fused with Reciprocal Rank Fusion |
| 3 | **Rerank** | Court-hierarchy boost; down-rank negative-treatment authorities | Cross-encoder rescoring + hierarchy/recency/citation-count boosts |
| 4 | **Pack** | Top-k passages, `has_statute` flag | Token-budgeted assembly with diversity + coverage guarantees |
| 5 | **Answer** | `MockProvider` (deterministic) | Ollama (local) or Claude, constrained to an allowed-citations list, streamed |
| 6 | **Verify** | Existence + negative-treatment + overstatement checks | + pin-cite accuracy, court-hierarchy compliance, semantic claim-support |
| 7 | **Render** | Append scope disclaimer + build id | Same, plus full provenance metadata |

## Stage 6: the anti-hallucination gate

The verify stage is the reason the system can be trusted in a legal setting. For
every citation extracted from the generated answer:

1. **Existence** — does it resolve to an authority **in the evidence pack**? A
   citation that resolves nowhere (or resolves but wasn't in the retrieved
   evidence) is treated as ungrounded and **stripped**.
2. **Negative treatment** — if the cited authority is overruled/repealed/superseded
   and the answer doesn't say so, the citation is stripped.
3. **Overstatement** — definitive language ("always", "guarantees", "will prevail")
   with no hedging is flagged.

Stripping is done at the **sentence** level: the offending sentence is removed
entirely. Citations are masked to placeholders before sentence segmentation so
internal periods (`State v.`, `Wn.2d`, `art.`) are never mistaken for sentence
boundaries.

The production verify stage adds two checks this demo omits (they need the full
corpus / an embedding model): **pin-cite accuracy** (does the cited subsection
text actually exist in the passage?) and **semantic claim support** (does the
passage actually support the sentence's assertion?).

## Evaluation metrics

The production harness scores ten automated metrics (M1–M10). The demo implements
the six that don't require the real corpus or an LLM judge:

| Metric | Target | Meaning |
|--------|--------|---------|
| **M1** Zero invented citations shown | 100% | No hallucinated citation survives to the user |
| **M2** Required-authority recall | ≥ 90% | The must-have authorities are retrieved into evidence |
| **M3** Controlling authority in top-5 | ≥ 85% | The dispositive authority ranks highly |
| **M6** Refusal accuracy | ≥ 95% | Refuses exactly when it should, answers when it should |
| **M9** Response length | ≥ 90% | Answers stay within the length budget |
| **M10** Build disclaimer | 100% | Every answer carries a disclaimer + build metadata |

Omitted in the demo (corpus/LLM-judge dependent): M4 claim-to-evidence coverage,
M5 pin-cite accuracy, M7 negative-authority avoidance, M8 hierarchy compliance.

## Design choices worth noting

- **Pluggable provider.** `LLMProvider` is a `Protocol`; the demo ships a
  `MockProvider`, production swaps in Ollama or Claude. Nothing else changes.
- **Allowed-citations constraint.** The answer stage only sees the packed
  evidence; the verify stage enforces that the answer cites nothing outside it.
  Generation and verification are independent, so a model mistake can't slip
  through silently.
- **Refusal is first-class.** No grounded evidence → an explicit refusal, never a
  guess. This is what keeps M1 at 100%.
