from __future__ import annotations

import json

from _bootstrap import ROOT

from cloud_expert.evidence_packages.builder import build_evidence_packages, make_session
from cloud_expert.evidence_packages.validation import (
    evidence_package_counts,
    validate_evidence_package_idempotency,
)


def main() -> int:
    with make_session() as session:
        before = evidence_package_counts(session)
        build_evidence_packages(session)
        after = evidence_package_counts(session)
        result = validate_evidence_package_idempotency(before, after)
    output = ROOT / "reports" / "evidence_packages" / "validate_idempotency.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
