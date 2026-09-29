from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

import _bootstrap  # noqa: F401

from cloud_expert.database.session import SessionLocal
from cloud_expert.pricing.huawei_promotion import extract_tax_policy, promote_quote


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Promote exact-quantity Huawei quotes, not review approvals"
    )
    parser.add_argument(
        "--quote-unit",
        action="append",
        required=True,
        help="quote Evidence ID:unit Evidence ID[:component size Evidence ID]",
    )
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--report-dir", type=Path, required=True)
    args = parser.parse_args()
    if args.report_dir.exists():
        parser.error("report directory must be new")
    with SessionLocal() as session:
        tax = extract_tax_policy(session)
        rows = []
        for pair in args.quote_unit:
            values = [int(value) for value in pair.split(":")]
            if len(values) not in {2, 3}:
                parser.error("quote-unit requires two or three evidence IDs")
            rows.append(
                promote_quote(
                    session,
                    values[0],
                    values[1],
                    tax.id,
                    size_evidence_id=values[2] if len(values) == 3 else None,
                )
            )
        report = {
            "recorded_at": datetime.now(UTC).isoformat(),
            "applied": args.apply,
            "tax_evidence_id": tax.id,
            "prices": rows,
            "obs_storage_period_promoted": False,
            "customer_approved": False,
        }
        if args.apply:
            session.commit()
        else:
            session.rollback()
    args.report_dir.mkdir(parents=True)
    (args.report_dir / "promotion.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
