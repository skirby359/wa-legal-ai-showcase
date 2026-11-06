# Architecture

This document maps the showcase to the production system stage-by-stage. The
shapes and control flow are faithful; the data and models are sanitized.

## The 7-stage pipeline

```
Question → Rewrite → Retrieve → Rerank → Pack → Answer → Verify → Render
```

| # | Stage | Showcase (`pipeline.py`) | Production |
|---|-------|--------------------------|------------|
| 1 | **Rewrite** | Tokenize into search terms; refuse content-free input | LLM decomposes the question into legal issues and statute hints; refuses out-of-scope |
| 2 | **Retrieve** | Keyword overlap against the corpus | BM25 + dense vector search + citation and chapter lookups, fused with Reciprocal Rank Fusion |
| 3 | **Rerank** | Court-hierarchy boost; down-rank negative-treatment authorities | Cross-encoder rescoring + hierarchy/recency/citation-count boosts |
| 4 | **Pack** | Top-k passages, `has_statute` flag | Token-budgeted assembly with diversity + coverage guarantees |
| 5 | **Answer** | `MockProvider` (deterministic) | Ollama (local) or Claude, constrained to an allowed-citations list, streamed |
| 6 | **Verify** | Existence + negative history + overstatement; then the negative-history note | + pin-cite accuracy, court-hierarchy compliance; semantic claim support is judged in evaluation |
| 7 | **Render** | Append scope disclaimer + build id | Same, plus full provenance metadata |

## Stage 6: the anti-hallucination gate

The verify stage is the reason the system can be trusted in a legal setting. For
every citation extracted from the generated answer:

1. **Existence** — does it resolve to an authority **in the evidence pack**? A
   citation that resolves nowhere (or resolves but wasn't in the retrieved
   evidence) is treated as ungrounded and **stripped**.
2. **Negative history** — if the cited authority is overruled, abrogated,
   superseded or repealed, does every sentence that cites it say so? If not,
   the citation is **kept** and a note is inserted right after it (after any
   parallel cites and year):
   `[negative history: OVERRULED — verify before relying on this authority]`.
   The check is then re-run on the final text, and checks that pass only
   because of the note are marked `status_annotated`.
3. **Overstatement** — definitive language ("always", "guarantees", "will prevail")
   with no hedging is flagged.

Two modes, as in production: `full` (detect, then strip) for the pipeline, and
`audit` (detect only, text unchanged) for agent mode, which sends failures back
to the model instead.

Stripping is done at the **sentence** level: the offending sentence is removed
entirely. Citations are masked to placeholders before sentence segmentation so
internal periods (`State v.`, `Wn.2d`, `art.`) are never mistaken for sentence
boundaries. Case-name matches are trimmed back at sentence breaks and leading
words, so "Under State v. Northup" cites `State v. Northup`.

**Why annotate negative history instead of stripping it.** Production derives
authority status from its citation graph, so it is machine-derived. A case
"overruled on other grounds" is still good law for other points. Deleting the
citation would hide a real authority. The note keeps it and makes the warning
impossible to miss. The note was added after a dev-split run showed a local
model citing labelled overruled, abrogated and superseded cases as good law,
despite the label in its evidence and an instruction to mention it.

The production verify stage adds checks this demo omits (they need the full
corpus): **pin-cite accuracy** (does the cited subsection or paragraph exist?)
and **hierarchy compliance** (was a higher court's authority available?).
Semantic claim support is graded by an LLM judge in evaluation.

## Agent mode (`agent.py`)

```
plan ──► tools ──► plan …
  └──► draft ──► audit ──► finalize
                   └──► revise ──► audit
```

| Piece | Showcase | Production |
|-------|----------|------------|
| Loop | Plain Python loop | LangGraph `StateGraph` |
| Tools | `search_authorities`, `read_authority`, `follow_citation`, `audit_citations` as functions | The same four, served by a FastMCP stdio server the agent spawns once per run |
| Planner | `ScriptedPlanner`: search, read hits, follow citations one hop, read, draft | Any chat model (Ollama, Claude, OpenAI) choosing tools turn by turn |
| Evidence | Ledger of authorities read; pack chosen **by code** with the pipeline's rerank and size limit | Same, with the pipeline's limits (15 passages, 4 per authority, 10K tokens) |
| Citation graph | Built from the citations inside each authority's text | 881K citation edges in Postgres |
| Audit | `verify(mode="audit")`; any unresolved citation or unqualified negative history triggers one revision | Same verifier, same rule |
| Gate | Unresolved after revision → "could not verify", naming the citations | Same |
| Finalize | `annotate_negative_history` + `render`, shared with the pipeline | Same |
| Caps | `max_tool_calls`, `max_revisions` | Tool calls, LLM calls, tokens, wall-clock, recursion limit |
| Trace | `TraceStep` list, printed with `--trace` | JSONL: tokens, cost, latency, stop reason per call |

**What keeps the A/B fair.** Only evidence gathering and the audit loop differ.
Both arms return the same `PipelineResult` shape, go through one scoring
function (`evaluation/runner.py`, the production harness's `answerer=` hook), and
share the refusal rules, answer model, pack limits, hierarchy ordering,
verifier, note and renderer. A metric with nothing to score shows `n/a` rather
than a vacuous 100%.

**Production result (dev split, 104 questions, both arms on a local 9B model).**
Agency did not improve the harness metrics: recall 73% vs 87%, 18 answers
"could not verify", 2.4× latency. The experiment's main finding was about the
baseline: it wrote uncited prose in 41% of answers, which passes a citation
verifier vacuously, and it was running with a truncated context window. Fixing
the window cut uncited answers to 24%. The agent has not been re-run since.

## Evaluation metrics

The production harness scores ten automated metrics (M1–M10). The demo implements
the seven that don't require the real corpus or an LLM judge:

| Metric | Target | Meaning |
|--------|--------|---------|
| **M1** Zero invented citations shown | 100% | No hallucinated citation survives to the user (measured on the final text) |
| **M2** Required-authority recall | ≥ 90% | The must-have authorities are retrieved into evidence |
| **M3** Controlling authority in top-5 | ≥ 85% | The dispositive authority ranks highly |
| **M6** Refusal accuracy | ≥ 95% | Refuses exactly when it should, answers when it should ("could not verify" counts as a refusal) |
| **M7** Negative-authority avoidance | ≥ 95% | No overruled/repealed authority is shown as good law; the detail counts answers saved only by the note |
| **M9** Response length | ≥ 90% | Answers stay within the length budget |
| **M10** Build disclaimer | 100% | Every answer carries a disclaimer + build metadata |

Omitted in the demo (corpus/LLM-judge dependent): M4 claim-to-evidence coverage,
M5 pin-cite accuracy, M8 hierarchy compliance.

`walegal-demo eval --arm agent` scores agent mode; `walegal-demo compare` puts
both arms side by side with their outcomes (answered / could not verify /
refused), answers citing nothing, notes added, and tool and model calls per
question.

## Tests

`tests/conftest.py` blocks every network connection for the whole suite
(`socket.connect`, `connect_ex`, `create_connection`), and
`tests/test_network_guard.py` proves it. Production's equivalent wraps the HTTP
client the vendor SDKs use and fails any test that tries to reach a paid LLM
API. It is a guard in the harness, because removing an API key from the
environment proved unreliable.

## Design choices worth noting

- **Pluggable provider.** `LLMProvider` is a `Protocol`; the demo ships a
  `MockProvider`, production swaps in Ollama or Claude. Nothing else changes.
- **Allowed-citations constraint.** The answer stage only sees the packed
  evidence; the verify stage enforces that the answer cites nothing outside it.
  Generation and verification are independent, so a model mistake can't slip
  through silently.
- **Refusal is first-class.** No grounded evidence → an explicit refusal, never a
  guess. This is what keeps M1 at 100%.
- **Metrics that can fail.** M1 is measured on the final text, not assumed from
  the strip step. M7 reports how much of its score the note supplied. A
  metric with no applicable questions says so.
- **Images from real output.** `docs/build_svgs.py` runs the CLI in-process and
  renders what it prints, so the README cannot drift from the code.
