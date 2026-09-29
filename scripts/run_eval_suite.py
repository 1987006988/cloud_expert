from __future__ import annotations

import argparse
import json
from pathlib import Path

import _bootstrap  # noqa: F401

from cloud_expert.evals.suite import SUITE_CODE, run_suite

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the synthetic deterministic Eval subset.")
    parser.add_argument("--suite", required=True, choices=[SUITE_CODE])
    args = parser.parse_args()
    result = run_suite()
    result["requested_suite"] = args.suite
    output = ROOT / "reports/evals/eval_results.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    print(
        json.dumps(
            {
                key: value
                for key, value in result.items()
                if key not in {"results", "case_inventory"}
            },
            indent=2,
            ensure_ascii=False,
        )
    )
    return 0 if not result["critical_failures"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
