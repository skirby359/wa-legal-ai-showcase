"""Command-line interface for the showcase.

    walegal-demo query "..."                   run one question through the pipeline
    walegal-demo query "..." --agent --trace   answer it in agent mode and show the tool trace
    walegal-demo eval [--arm agent]            run the gold set and print the metric table
    walegal-demo compare                       A/B both arms on the gold set, same scoring

Make the mock model misbehave (query, eval and compare):
    --hallucinate     invent a citation that is not in the evidence
    --overstate       use definitive language with no hedging
    --cite-overruled  cite an overruled case as good law
    --stubborn        (agent) keep the invented citation when asked to revise
"""

from __future__ import annotations

import argparse
import sys

from walegal_demo.agent import run_agent
from walegal_demo.corpus import get_corpus
from walegal_demo.evaluation.runner import run_evaluation
from walegal_demo.evaluation.types import MetricScore, QuestionResult
from walegal_demo.pipeline import run_pipeline
from walegal_demo.provider import MockProvider

_FAULTS = ("hallucinate", "overstate", "cite_overruled", "stubborn")


def _provider(args: argparse.Namespace) -> MockProvider:
    return MockProvider(**{f: getattr(args, f) for f in _FAULTS})


def _cmd_query(args: argparse.Namespace) -> int:
    run = run_agent if args.agent else run_pipeline
    result = run(args.question, get_corpus(), _provider(args))

    print("\n=== QUESTION ===")
    print(args.question)

    if args.agent and args.trace:
        print("\n=== AGENT TRACE ===")
        if not result.trace:
            print("(no steps: refused before any tool call)")
        for i, step in enumerate(result.trace, 1):
            print(f"{i:>3}. {step.kind:<5} {step.name}")
            if step.detail:
                print(f"         -> {step.detail}")

    if result.outcome == "refused":
        print("\n=== REFUSED ===")
        print(result.refusal_reason)
        return 0

    if any(getattr(args, f) for f in _FAULTS):
        print("\n=== RAW ANSWER (pre-verification, straight from the model) ===")
        print(result.raw_answer_text)

    v = result.verification
    title = "AUDIT (agent, after revision)" if args.agent else "VERIFICATION (Stage 6)"
    print(f"\n=== {title} ===")
    print(f"citations checked: {v.citations_checked} | "
          f"passed: {v.citations_passed} | stripped: {v.citations_stripped} "
          f"({v.stripped_ratio:.0%} unresolved)  -> {'PASSED' if v.passed else 'FAILED'}")
    for flag in v.flags:
        print(f"  - {flag}")

    if result.outcome == "could_not_verify":
        print("\n=== COULD NOT VERIFY (what the user sees) ===")
        print(result.rendered_text)
        return 0

    print("\n=== FINAL ANSWER (what the user sees) ===")
    print(result.rendered_text)
    return 0


def _print_scores(scores: list[MetricScore]) -> bool:
    width = max(len(s.name) for s in scores)
    print(f"{'METRIC'.ljust(width)}   TARGET   ACTUAL   STATUS   DETAIL")
    print("-" * (width + 50))
    all_pass = True
    for s in scores:
        all_pass &= s.passed
        status = "PASS" if s.passed else "FAIL"
        actual = f"{s.actual:>5.0%}" if s.applicable else "  n/a"
        print(f"{s.name.ljust(width)}   {s.target:>5.0%}   {actual}   "
              f"{status:<6}   {s.detail}")
    print("-" * (width + 50))
    return all_pass


def _cmd_eval(args: argparse.Namespace) -> int:
    results, scores = run_evaluation(args.arm, _provider(args))
    print(f"\nRan {len(results)} questions through the {args.arm} arm.\n")
    all_pass = _print_scores(scores)
    print(f"\nOVERALL: {'ALL METRICS PASS' if all_pass else 'SOME METRICS FAILED'}")
    return 0 if all_pass else 1


def _outcomes(results: list[QuestionResult]) -> str:
    n = {k: sum(r.outcome == k for r in results)
         for k in ("answered", "could_not_verify", "refused")}
    return f"{n['answered']} / {n['could_not_verify']} / {n['refused']}"


def _per_question(results: list[QuestionResult], attr: str) -> str:
    answered = [r for r in results if not r.refused or r.outcome == "could_not_verify"]
    if not answered:
        return "-"
    return f"{sum(getattr(r, attr) for r in answered) / len(answered):.1f}"


def _cmd_compare(args: argparse.Namespace) -> int:
    provider = _provider(args)
    base_results, base_scores = run_evaluation("baseline", provider)
    agent_results, agent_scores = run_evaluation("agent", provider)

    rows: list[tuple[str, str, str]] = []
    for b, a in zip(base_scores, agent_scores):
        def fmt(s: MetricScore) -> str:
            if not s.applicable:
                return "n/a"  # nothing to score, e.g. every answer was refused
            return f"{s.actual:.0%}{'' if s.passed else ' FAIL'}"
        rows.append((b.name, fmt(b), fmt(a)))
    rows += [
        ("outcomes: answered / could-not-verify / refused",
         _outcomes(base_results), _outcomes(agent_results)),
        ("answers citing nothing",
         str(sum(not r.refused and r.citations_shown == 0 for r in base_results)),
         str(sum(not r.refused and r.citations_shown == 0 for r in agent_results))),
        ("answers with a negative-history note added",
         str(sum(r.negative_annotated for r in base_results)),
         str(sum(r.negative_annotated for r in agent_results))),
        ("tool calls per question", _per_question(base_results, "tool_calls"),
         _per_question(agent_results, "tool_calls")),
        ("model calls per question", _per_question(base_results, "llm_calls"),
         _per_question(agent_results, "llm_calls")),
    ]
    width = max(len(r[0]) for r in rows)
    print(f"\nA/B on {len(base_results)} gold questions: same corpus, same mock model, "
          f"same verifier, same scoring.\n")
    print(f"{''.ljust(width)}   {'BASELINE':>10}   {'AGENT':>10}")
    print("-" * (width + 28))
    for name, b, a in rows:
        print(f"{name.ljust(width)}   {b:>10}   {a:>10}")
    print("-" * (width + 28))
    return 0


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):  # a console that can't print "—" or "§"
        sys.stdout.reconfigure(errors="replace")

    parser = argparse.ArgumentParser(prog="walegal-demo", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    def add_faults(p: argparse.ArgumentParser) -> None:
        p.add_argument("--hallucinate", action="store_true",
                       help="make the mock LLM invent a citation (watch verify strip it)")
        p.add_argument("--overstate", action="store_true",
                       help="make the mock LLM use definitive language (watch the overstatement flag)")
        p.add_argument("--cite-overruled", action="store_true",
                       help="make the mock LLM cite an overruled case as good law (watch the note)")
        p.add_argument("--stubborn", action="store_true",
                       help="agent mode: the mock LLM keeps an invented citation when asked to revise")

    q = sub.add_parser("query", help="run one question through the pipeline or the agent")
    q.add_argument("question", help="the legal question to ask")
    q.add_argument("--agent", action="store_true", help="answer in agent mode")
    q.add_argument("--trace", action="store_true", help="agent mode: print the tool trace")
    add_faults(q)
    q.set_defaults(func=_cmd_query)

    e = sub.add_parser("eval", help="run the gold set and print the metric table")
    e.add_argument("--arm", choices=("baseline", "agent"), default="baseline",
                   help="answer with the pipeline (baseline) or agent mode")
    add_faults(e)
    e.set_defaults(func=_cmd_eval)

    c = sub.add_parser("compare", help="A/B the pipeline and agent mode on the gold set")
    add_faults(c)
    c.set_defaults(func=_cmd_compare)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
