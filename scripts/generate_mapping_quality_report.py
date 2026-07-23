from __future__ import annotations

import json

from _bootstrap import ROOT

from cloud_expert.mapping.pipeline import make_session
from cloud_expert.mapping.reports import write_mapping_reports


def main() -> int:
    with make_session() as session:
        summary = write_mapping_reports(session, ROOT / "reports" / "mapping")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if summary["candidates"] > 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
