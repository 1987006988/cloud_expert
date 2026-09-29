from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import _bootstrap  # noqa: F401
from run_model_review import _build_findings
from sqlalchemy import select
from sqlalchemy.orm import Session

from cloud_expert.database.models.review import ModelReviewFinding, ModelReviewRun
from cloud_expert.database.session import SessionLocal
from cloud_expert.review.consensus import (
    MODEL,
    ReviewOpinion,
    arbitrate,
    fingerprint,
    validate_manifest,
)

POLICY_VERSION = "dual_model_consensus_v1"


def _load(path: Path, stage: str) -> tuple[dict[str, Any], list[ReviewOpinion]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{stage} manifest must be a JSON object")
    return payload, validate_manifest(payload, stage)


def _add_stage_run(
    session: Session,
    stage: str,
    manifest: dict[str, Any],
    items: list[ReviewOpinion],
    precheck_code: str,
) -> ModelReviewRun:
    content_hash = fingerprint(manifest)
    run_code = f"{stage}_{content_hash[:16]}"
    existing = session.scalar(select(ModelReviewRun).where(ModelReviewRun.run_code == run_code))
    if existing is not None:
        return existing
    run = ModelReviewRun(
        run_code=run_code,
        policy_version=POLICY_VERSION,
        reviewer_model=MODEL,
        input_fingerprint=content_hash,
        reviewed_at=datetime.now(UTC),
        summary_json={
            "stage": stage,
            "precheck_run_code": precheck_code,
            "manifest_sha256": content_hash,
            "review_session_id": manifest["review_session_id"],
            "subject_count": len(items),
            "self_declared_model": MODEL,
            "model_origin_attested_by_tool": False,
        },
    )
    session.add(run)
    session.flush()
    session.add_all(
        ModelReviewFinding(
            run_id=run.id,
            subject_type=item.subject_type,
            subject_id=item.subject_id,
            verdict=item.verdict,
            reason_code=item.reason_code,
            rationale=item.rationale,
            evidence_ids=list(item.evidence_ids),
            input_hash=item.input_hash,
        )
        for item in items
    )
    return run


def process(
    precheck_code: str, primary_path: Path, adversarial_path: Path, *, apply: bool = False
) -> dict[str, Any]:
    primary_manifest, primary_items = _load(primary_path, "primary")
    adversarial_manifest, adversarial_items = _load(adversarial_path, "adversarial")
    if primary_manifest["review_session_id"] == adversarial_manifest["review_session_id"]:
        raise ValueError("primary and adversarial reviews must use different sessions")
    if any(
        manifest.get("precheck_run_code") != precheck_code
        for manifest in (primary_manifest, adversarial_manifest)
    ):
        raise ValueError("review manifests must target the selected precheck run")
    with SessionLocal() as session:
        precheck = session.scalar(
            select(ModelReviewRun).where(ModelReviewRun.run_code == precheck_code)
        )
        if precheck is None or precheck.reviewer_model != "deterministic_evidence_precheck":
            raise ValueError("selected run is not a deterministic precheck")
        precheck_findings = {
            (row.subject_type, row.subject_id): row
            for row in session.scalars(
                select(ModelReviewFinding).where(ModelReviewFinding.run_id == precheck.id)
            )
        }
        primary = {item.key: item for item in primary_items}
        adversarial = {item.key: item for item in adversarial_items}
        current_inputs = {(row.subject_type, row.subject_id): row for row in _build_findings()}
        for stage, items in (("primary", primary), ("adversarial", adversarial)):
            for key, item in items.items():
                baseline = precheck_findings.get(key)
                if baseline is None:
                    raise ValueError(f"{stage} cites unknown subject {key}")
                current = current_inputs.get(key)
                if current is None or current.input_hash != baseline.input_hash:
                    raise ValueError(f"{stage} review input changed since the precheck for {key}")
                if item.input_hash != baseline.input_hash:
                    raise ValueError(f"{stage} cites stale input for {key}")
                if not set(item.evidence_ids).issubset(set(baseline.evidence_ids)):
                    raise ValueError(f"{stage} cites unverified evidence for {key}")
        reviewed_keys = sorted(primary.keys() & adversarial.keys())
        conclusions = {
            key: arbitrate(
                precheck_findings[key].verdict,
                precheck_findings[key].input_hash,
                tuple(precheck_findings[key].evidence_ids),
                primary[key],
                adversarial[key],
            )
            for key in reviewed_keys
        }
        counts = dict(Counter(item.verdict for item in conclusions.values()))
        summary: dict[str, Any] = {
            "policy_version": POLICY_VERSION,
            "precheck_run_code": precheck_code,
            "total_precheck_subjects": len(precheck_findings),
            "primary_reviewed": len(primary),
            "adversarial_reviewed": len(adversarial),
            "jointly_reviewed": len(reviewed_keys),
            "unreviewed": len(precheck_findings) - len(reviewed_keys),
            "arbitration_counts": counts,
            "customer_eligibility_granted": False,
            "model_origin_attested_by_tool": False,
        }
        if not apply:
            return {**summary, "applied": False}
        if not reviewed_keys:
            raise ValueError("no subjects have both independent reviews")
        primary_run = _add_stage_run(
            session, "primary", primary_manifest, primary_items, precheck_code
        )
        adversarial_run = _add_stage_run(
            session, "adversarial", adversarial_manifest, adversarial_items, precheck_code
        )
        arbitration_hash = fingerprint(
            {
                "policy": POLICY_VERSION,
                "precheck": precheck_code,
                "primary": primary_run.run_code,
                "adversarial": adversarial_run.run_code,
            }
        )
        run_code = f"arbitration_{arbitration_hash[:16]}"
        existing = session.scalar(select(ModelReviewRun).where(ModelReviewRun.run_code == run_code))
        if existing is None:
            summary["stage"] = "arbitration"
            summary["primary_run_code"] = primary_run.run_code
            summary["adversarial_run_code"] = adversarial_run.run_code
            summary["conditions_by_subject"] = {
                f"{key[0]}:{key[1]}": list(item.conditions)
                for key, item in conclusions.items()
                if item.conditions
            }
            run = ModelReviewRun(
                run_code=run_code,
                policy_version=POLICY_VERSION,
                reviewer_model="dual_model_arbitration",
                input_fingerprint=arbitration_hash,
                reviewed_at=datetime.now(UTC),
                summary_json=summary,
            )
            session.add(run)
            session.flush()
            session.add_all(
                ModelReviewFinding(
                    run_id=run.id,
                    subject_type=key[0],
                    subject_id=key[1],
                    verdict=item.verdict,
                    reason_code=item.reason_code,
                    rationale=item.rationale,
                    evidence_ids=list(item.evidence_ids),
                    input_hash=precheck_findings[key].input_hash,
                )
                for key, item in conclusions.items()
            )
        session.commit()
        return {
            **summary,
            "run_code": run_code,
            "applied": True,
            "already_recorded": existing is not None,
        }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--precheck-run-code", required=True)
    parser.add_argument("--primary", type=Path, required=True)
    parser.add_argument("--adversarial", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    try:
        result = process(args.precheck_run_code, args.primary, args.adversarial, apply=args.apply)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"valid": False, "error": str(exc)}, ensure_ascii=False, indent=2))
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
