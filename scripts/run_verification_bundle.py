"""Plan by default; execute only the fixed, isolated offline verification commands."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import _bootstrap  # noqa: F401

from cloud_expert.evals.verification_run import run_verification, validate_verification_bundle

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--execute", action="store_true")
    mode.add_argument("--verify-sha256", help="Independently retained manifest SHA; no execution.")
    args = parser.parse_args()
    try:
        if args.verify_sha256:
            result = validate_verification_bundle(
                args.output_dir, expected_manifest_sha256=args.verify_sha256
            )
        else:
            result = run_verification(ROOT, args.output_dir, execute=args.execute)
    except (OSError, ValueError) as exc:
        print(json.dumps({"passed": False, "error": str(exc)}))
        return 2
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result["status"] == "planned" or result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
