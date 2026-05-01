"""
Deterministic replay runner for the Post Fiat agent smoke pack.

Reads JSON fixtures from ./fixtures, validates the recorded agent response
against the contract in harness/contract.py, and writes a stable JSON result
file plus a human-readable summary to stdout.

Determinism notes:
  * No clocks, no RNG, no network, no model calls.
  * Fixtures are loaded in lexicographic filename order.
  * Findings within a case are stable in the order the validators emit them.
  * JSON output uses sort_keys=True and a fixed indent.

Exit code is 0 on a clean run (no `fail` outcomes that weren't
`expected_outcome="fail"`), 1 otherwise. Matches CI conventions.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any

from contract import (
    Finding,
    validate_structured_output,
    validate_tool_call,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURES_DIR = REPO_ROOT / "fixtures"
RESULTS_DIR = REPO_ROOT / "results"


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------

def load_cases(fixtures_dir: Path) -> list[dict[str, Any]]:
    """Load all replay cases. Sorted by filename for determinism."""
    cases: list[dict[str, Any]] = []
    for path in sorted(fixtures_dir.glob("case_*.json")):
        with path.open() as f:
            data = json.load(f)
        data["_fixture_path"] = path.name
        cases.append(data)
    return cases


def load_triage(fixtures_dir: Path) -> dict[str, Any]:
    triage_path = fixtures_dir / "issue_triage.json"
    if not triage_path.exists():
        return {}
    with triage_path.open() as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Replay
# ---------------------------------------------------------------------------

def replay_case(case: dict[str, Any]) -> dict[str, Any]:
    """Replay one fixture and produce a result record."""
    name = case["name"]
    expected_outcome = case["expected_outcome"]  # pass | warn | fail
    response = case.get("recorded_response", {})

    findings: list[Finding] = []

    # 1. Structured output. The fixture may include either a parsed object
    #    or a raw string (to simulate malformed JSON from the model).
    raw = response.get("structured_output_raw")
    parsed = response.get("structured_output")
    if raw is not None and parsed is None:
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            findings.append(Finding(
                code="STRUCT_INVALID_JSON",
                message=f"structured_output_raw is not valid JSON: {exc.msg}",
                severity="fail",
            ))
            parsed = None

    if parsed is not None or raw is None:
        # Skip structured validation only if we already failed on JSON parse.
        findings.extend(validate_structured_output(parsed if parsed is not None else {}))

    # 2. Tool call.
    findings.extend(validate_tool_call(
        tool=response.get("tool_call"),
        expected_tool=case.get("expected_tool"),
        expected_args=case.get("expected_tool_args"),
    ))

    # Resolve outcome from findings.
    if any(f.severity == "fail" for f in findings):
        actual_outcome = "fail"
    elif any(f.severity == "warn" for f in findings):
        actual_outcome = "warn"
    else:
        actual_outcome = "pass"

    matched = actual_outcome == expected_outcome

    return {
        "name": name,
        "fixture": case["_fixture_path"],
        "expected_outcome": expected_outcome,
        "actual_outcome": actual_outcome,
        "matched": matched,
        "findings": [asdict(f) for f in findings],
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def render_summary(results: list[dict[str, Any]], triage: dict[str, Any]) -> str:
    lines = ["Post Fiat Agent Replay Smoke Pack — run summary", "=" * 49, ""]
    width = max(len(r["name"]) for r in results)
    for r in results:
        marker = "OK " if r["matched"] else "!! "
        lines.append(
            f"  {marker}{r['name']:<{width}}  expected={r['expected_outcome']:<4}  "
            f"actual={r['actual_outcome']:<4}  findings={len(r['findings'])}"
        )
    lines.append("")
    matched = sum(1 for r in results if r["matched"])
    lines.append(f"  {matched}/{len(results)} cases matched expected outcome.")
    if triage:
        cats = sorted({i["category"] for i in triage.get("issues", [])})
        lines.append(f"  Triage categories present: {', '.join(cats)}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--fixtures",
        type=Path,
        default=FIXTURES_DIR,
        help=f"fixtures directory (default: {FIXTURES_DIR})",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=RESULTS_DIR / "run.json",
        help="path for JSON result file",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="exit non-zero if any case did not match its expected_outcome",
    )
    args = parser.parse_args(argv)

    cases = load_cases(args.fixtures)
    if not cases:
        print(f"no fixtures found in {args.fixtures}", file=sys.stderr)
        return 2

    results = [replay_case(c) for c in cases]
    triage = load_triage(args.fixtures)

    # Build result document.
    matched = sum(1 for r in results if r["matched"])
    document = {
        "harness_version": "1.0.0",
        "contract": "post_fiat.task_node.task_generation/v1",
        "summary": {
            "total": len(results),
            "matched": matched,
            "mismatched": len(results) - matched,
        },
        "cases": results,
        "triage": triage,
    }

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w") as f:
        json.dump(document, f, indent=2, sort_keys=True)
        f.write("\n")

    print(render_summary(results, triage))
    print(f"\nFull result: {args.out}")

    if args.check and matched != len(results):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
