from __future__ import annotations

import argparse
import json

from _bootstrap import ROOT

from cloud_expert.evidence_packages.builder import build_evidence_packages, make_session


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mapping-level", default=None)
    parser.add_argument("--market-mode", default=None)
    parser.add_argument("--source-provider", default=None)
    parser.add_argument("--target-provider", default=None)
    args = parser.parse_args()
    with make_session() as session:
        result = build_evidence_packages(session, args.mapping_level)
    output = ROOT / "reports" / "evidence_packages" / "package_results.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result.as_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result.as_dict(), ensure_ascii=False, indent=2))
    return 0 if result.packages > 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
