"""Command-line interface for the showcase.

    walegal-demo query "..."            run one question through the pipeline
    walegal-demo query "..." --hallucinate   make the mock LLM invent a citation
    walegal-demo eval                   run the gold set and print the metric table
"""

from __future__ import annotations

import argparse
import sys

from walegal_demo.corpus import get_corpus
from walegal_demo.evaluation.runner import run_evaluation
from walegal_demo.pipeline import run_pipeline
from walegal_demo.provider import MockProvider


def _cmd_query(args: argparse.Namespace) -> int:
    provider = MockProvider(hallucinate=args.hallucinate, overstate=args.overstate)
    result = run_pipeline(args.question, get_corpus(), provider)

    print("\n=== QUESTION ===")
    print(args.question)

    if result.refused:
        print("\n=== REFUSED ===")
        print(result.refusal_reason)
        return 0

    if args.hallucinate or args.overstate:
        print("\n=== RAW ANSWER (pre-verification, straight from the model) ===")
        print(result.raw_answer_text)

    v = result.verification
    print("\n=== VERIFICATION (Stage 6) ===")
    print(f"citations checked: {v.citations_checked} | "
          f"passed: {v.citations_passed} | stripped: {v.citations_stripped} "
          f"({v.stripped_ratio:.0%})  -> {'PASSED' if v.passed else 'FAILED'}")
    for flag in v.flags:
        print(f"  - {flag}")

    print("\n=== FINAL ANSWER (what the user sees) ===")
    print(result.rendered_text)
    return 0


def _cmd_eval(_args: argparse.Namespace) -> int:
    results, scores = run_evaluation()
    print(f"\nRan {len(results)} questions through the pipeline.\n")
    width = max(len(s.name) for s in scores)
    print(f"{'METRIC'.ljust(width)}   TARGET   ACTUAL   STATUS   DETAIL")
    print("-" * (width + 50))
    all_pass = True
    for s in scores:
        all_pass &= s.passed
        status = "PASS" if s.passed else "FAIL"
        print(f"{s.name.ljust(width)}   {s.target:>5.0%}   {s.actual:>5.0%}   "
              f"{status:<6}   {s.detail}")
    print("-" * (width + 50))
    print(f"\nOVERALL: {'ALL METRICS PASS' if all_pass else 'SOME METRICS FAILED'}")
    return 0 if all_pass else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="walegal-demo", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    q = sub.add_parser("query", help="run one question through the pipeline")
    q.add_argument("question", help="the legal question to ask")
    q.add_argument("--hallucinate", action="store_true",
                   help="make the mock LLM invent a citation (watch verify strip it)")
    q.add_argument("--overstate", action="store_true",
                   help="make the mock LLM use definitive language (watch the overstatement flag)")
    q.set_defaults(func=_cmd_query)

    e = sub.add_parser("eval", help="run the gold set and print the metric table")
    e.set_defaults(func=_cmd_eval)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
