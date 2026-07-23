from __future__ import annotations

import json

from _bootstrap import ROOT

from cloud_expert.evidence_packages.builder import make_session
from cloud_expert.evidence_packages.validation import validate_evidence_references


def main() -> int:
    with make_session() as session:
        result = validate_evidence_references(session)
    output = ROOT / "reports" / "evidence_packages" / "validate_evidence_references.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
