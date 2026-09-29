from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any

import _bootstrap  # noqa: F401
from sqlalchemy import select

from cloud_expert.database.enums import MappingCandidateStatus, ReviewStatus
from cloud_expert.database.models.mapping import MappingCandidate, MappingReview
from cloud_expert.database.session import SessionLocal
from cloud_expert.market.mapping_integrity import _entity_product

REPORT_ROOT = Path("reports/market/mapping_scope_repair")


def repair(*, apply: bool = False) -> dict[str, Any]:
    with SessionLocal() as session:
        old_candidates = session.scalars(
            select(MappingCandidate)
            .where(MappingCandidate.rule_set.has(market_mode="cross_market"))
            .order_by(MappingCandidate.id)
        ).all()
        replacements: list[tuple[MappingCandidate, MappingCandidate]] = []
        for old in old_candidates:
            source = _entity_product(session, old.source_entity_type, old.source_entity_id)
            target = _entity_product(session, old.target_entity_type, old.target_entity_id)
            if source is None or target is None or source.market_mode != target.market_mode:
                continue
            if old.superseded_by_id is not None:
                continue
            if old.candidate_status in {
                MappingCandidateStatus.REJECTED.value,
                MappingCandidateStatus.SUPERSEDED.value,
            }:
                continue
            if old.review_status != ReviewStatus.PENDING_REVIEW.value or session.scalar(
                select(MappingReview.id).where(MappingReview.mapping_candidate_id == old.id)
            ):
                raise ValueError(
                    f"reviewed candidate requires manual-history preservation: {old.id}"
                )
            new = session.scalar(
                select(MappingCandidate).where(
                    MappingCandidate.rule_set.has(
                        rule_set_code=f"{old.rule_set.rule_set_code}_{source.market_mode}",
                        market_mode=source.market_mode,
                    ),
                    MappingCandidate.source_entity_type == old.source_entity_type,
                    MappingCandidate.source_entity_id == old.source_entity_id,
                    MappingCandidate.target_entity_type == old.target_entity_type,
                    MappingCandidate.target_entity_id == old.target_entity_id,
                    MappingCandidate.mapping_level == old.mapping_level,
                )
            )
            if new is None:
                raise ValueError(f"missing same-market replacement for candidate {old.id}")
            if old.evidence_links and not new.evidence_links:
                raise ValueError(f"replacement lost all evidence for candidate {old.id}")
            replacements.append((old, new))
        identities = [(old.id, new.id) for old, new in replacements]
        digest = sha256(json.dumps(identities).encode("utf-8")).hexdigest()
        result: dict[str, Any] = {
            "input_fingerprint": digest,
            "superseded_candidates": len(replacements),
            "replacement_pairs": identities,
            "customer_eligibility_granted": False,
            "applied": apply,
        }
        if not apply:
            return result
        now = datetime.now(UTC)
        for old, new in replacements:
            old.candidate_status = MappingCandidateStatus.SUPERSEDED.value
            old.superseded_by_id = new.id
            old.valid_to = now
        session.commit()
    report_dir = REPORT_ROOT / f"run_{digest[:12]}"
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / "validation_results.json"
    if not report_path.exists():
        report_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    result["report_path"] = str(report_path)
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    try:
        result = repair(apply=args.apply)
    except ValueError as exc:
        print(json.dumps({"valid": False, "error": str(exc)}, indent=2))
        return 1
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
