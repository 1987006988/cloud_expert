from __future__ import annotations

import argparse
import json

from _bootstrap import ROOT
from sqlalchemy import func, select

from cloud_expert.database.enums import FreshnessStatus
from cloud_expert.database.models.evidence_package import EvidenceReference
from cloud_expert.evidence_packages.builder import make_session


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--all-providers", action="store_true")
    parser.parse_args()
    with make_session() as session:
        counts = {
            status: session.scalar(
                select(func.count())
                .select_from(EvidenceReference)
                .where(EvidenceReference.freshness_status == status)
            )
            or 0
            for status in FreshnessStatus.values()
        }
    result = {"freshness_counts": counts, "valid": counts["stale"] == 0}
    output = ROOT / "reports" / "evidence_packages" / "source_freshness.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
