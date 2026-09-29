"""Coordinator entry point; defaults to read-only composition, never source import."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import _bootstrap  # noqa: F401

from cloud_expert.database.session import SessionLocal
from cloud_expert.pricing.scoped_tco import (
    ScopedECSConfig,
    compose_scoped_tco,
    persist_scoped_tco,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Compose an explicitly scoped domestic ECS TCO")
    parser.add_argument("--config", type=Path, required=True, help="Explicit versioned JSON config")
    parser.add_argument(
        "--report-dir", type=Path, required=True, help="New immutable report directory"
    )
    parser.add_argument(
        "--apply", action="store_true", help="Coordinator only: persist in configured DB"
    )
    args = parser.parse_args()
    config = ScopedECSConfig.model_validate_json(args.config.read_text(encoding="utf-8-sig"))
    args.report_dir.mkdir(parents=True, exist_ok=False)
    with SessionLocal() as session:
        try:
            report = (
                persist_scoped_tco(session, config)
                if args.apply
                else compose_scoped_tco(session, config)
            )
            report["applied"] = args.apply
            # Write the immutable proposal before committing; a failed commit is
            # recorded separately so a proposal cannot masquerade as a receipt.
            proposal = {**report, "transaction_committed": False}
            (args.report_dir / "proposal.json").write_text(
                json.dumps(proposal, indent=2), encoding="utf-8"
            )
            if args.apply:
                session.commit()
            else:
                session.rollback()
            report["transaction_committed"] = args.apply
            (args.report_dir / "result.json").write_text(
                json.dumps(report, indent=2), encoding="utf-8"
            )
        except Exception:
            session.rollback()
            (args.report_dir / "failure.json").write_text(
                json.dumps(
                    {
                        "status": "failed",
                        "customer_eligible": False,
                        "verify_database_before_retry": True,
                    }
                ),
                encoding="utf-8",
            )
            raise
    print(
        json.dumps(
            {
                "report_dir": str(args.report_dir.resolve()),
                "status": report["completeness_status"],
                "applied": args.apply,
                "customer_eligible": False,
            }
        )
    )
    return 0 if report["completeness_status"] == "complete" else 2


if __name__ == "__main__":
    raise SystemExit(main())
