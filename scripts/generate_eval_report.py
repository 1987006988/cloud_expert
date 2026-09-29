from __future__ import annotations

import argparse
import json
from pathlib import Path

import _bootstrap  # noqa: F401

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description="Summarize an already executed Eval Suite.")
    parser.add_argument("--suite", required=True)
    args = parser.parse_args()
    path = ROOT / "reports/evals/eval_results.json"
    if not path.exists():
        raise SystemExit("Eval result is missing; run run_eval_suite.py first")
    result = json.loads(path.read_text(encoding="utf-8"))
    if result["suite_code"] != args.suite:
        raise SystemExit("requested suite does not match the recorded result")
    lines = [
        "# Eval Suite Inventory",
        "",
        f"- Suite: `{result['suite_code']}` / `{result['suite_version']}`",
        f"- Cases: {result['case_count']}",
        f"- Passed: {result['passed']}",
        f"- Failed: {result['failed']}",
        f"- Critical failures: {len(result['critical_failures'])}",
        f"- Full-chain coverage: {result['full_chain_coverage']}",
        "",
        "## Categories",
        "",
    ]
    lines.extend(
        f"- {category}: {counts['passed']}/{counts['total']}"
        for category, counts in sorted(result["category_counts"].items())
    )
    lines.extend(["", "## Gaps", ""])
    lines.extend(f"- {gap}" for gap in result["coverage_gaps"])
    lines.append("")
    lines.append(
        "This is a synthetic deterministic subset, not a 400-case full-chain acceptance suite. "
        "No model judge or live customer-output evaluation was run."
    )
    output = ROOT / "reports/evals/suite_inventory.md"
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(str(output))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
