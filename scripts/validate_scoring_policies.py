from __future__ import annotations

import json
from pathlib import Path

from _bootstrap import ROOT as _ROOT  # noqa: F401

from cloud_expert.decision.validation import validate_policy_directory


def main() -> int:
    result = validate_policy_directory(Path("config") / "decision" / "policies")
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return 0 if result["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
