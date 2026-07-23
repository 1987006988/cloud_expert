from __future__ import annotations

import json

from _bootstrap import ROOT

from cloud_expert.mapping.pipeline import generate_all_mapping_candidates, make_session


def main() -> int:
    with make_session() as session:
        result = generate_all_mapping_candidates(session)
    output = ROOT / "reports" / "mapping" / "last_generation_result.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result.as_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result.as_dict(), ensure_ascii=False, indent=2))
    return 0 if not result.errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
