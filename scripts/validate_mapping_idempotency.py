from __future__ import annotations

import json

from _bootstrap import ROOT

from cloud_expert.mapping.pipeline import generate_all_mapping_candidates, make_session
from cloud_expert.mapping.validation import mapping_counts, validate_mapping_idempotency


def main() -> int:
    with make_session() as session:
        before = mapping_counts(session)
        generate_all_mapping_candidates(session)
        after = mapping_counts(session)
        result = validate_mapping_idempotency(before, after)
    output = ROOT / "reports" / "mapping" / "validate_mapping_idempotency.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
