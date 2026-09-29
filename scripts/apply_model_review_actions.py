from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import _bootstrap  # noqa: F401
from run_model_review import _build_findings
from sqlalchemy import select

from cloud_expert.database.models.decision import CandidateDecisionResult, DecisionReview
from cloud_expert.database.models.mapping import MappingCandidate, MappingReview
from cloud_expert.database.models.review import ModelReviewFinding, ModelReviewRun
from cloud_expert.database.session import SessionLocal

POLICY_VERSION = "dual_model_consensus_v1"
REPORT_ROOT = Path("reports/model_review/actions")


def apply_actions(run_code: str, *, apply: bool = False) -> dict[str, Any]:
    with SessionLocal() as session:
        run = session.scalar(select(ModelReviewRun).where(ModelReviewRun.run_code == run_code))
        if (
            run is None
            or run.policy_version != POLICY_VERSION
            or run.reviewer_model != "dual_model_arbitration"
            or run.summary_json.get("stage") != "arbitration"
        ):
            raise ValueError("selected run is not a dual-model arbitration")
        reviewer = f"model_consensus:{run_code}"
        findings = session.scalars(
            select(ModelReviewFinding)
            .where(ModelReviewFinding.run_id == run.id)
            .order_by(ModelReviewFinding.subject_type, ModelReviewFinding.subject_id)
        ).all()
        if len(findings) != run.summary_json.get("jointly_reviewed"):
            raise ValueError("arbitration finding count does not match its manifest")
        current = {(item.subject_type, item.subject_id): item for item in _build_findings()}
        actions: list[dict[str, Any]] = []
        for finding in findings:
            if finding.verdict != "reject":
                actions.append(
                    {
                        "subject_type": finding.subject_type,
                        "subject_id": finding.subject_id,
                        "action": "retain_unresolved",
                        "verdict": finding.verdict,
                    }
                )
                continue
            key = (finding.subject_type, finding.subject_id)
            row: MappingCandidate | CandidateDecisionResult | None
            prior: MappingReview | DecisionReview | None
            if finding.subject_type == "mapping_candidate":
                row = session.get(MappingCandidate, finding.subject_id)
                prior = session.scalar(
                    select(MappingReview).where(
                        MappingReview.mapping_candidate_id == finding.subject_id,
                        MappingReview.reviewer == reviewer,
                    )
                )
                already_applied = (
                    row is not None
                    and row.candidate_status == "rejected"
                    and row.review_status == "rejected"
                    and prior is not None
                )
            elif finding.subject_type == "candidate_decision_result":
                row = session.get(CandidateDecisionResult, finding.subject_id)
                prior = session.scalar(
                    select(DecisionReview).where(
                        DecisionReview.candidate_result_id == finding.subject_id,
                        DecisionReview.reviewer == reviewer,
                    )
                )
                already_applied = (
                    row is not None and row.review_status == "rejected" and prior is not None
                )
            else:
                raise ValueError(f"unsupported rejection writeback type: {finding.subject_type}")
            if row is None:
                raise ValueError(f"missing subject {key}")
            if not already_applied and (
                key not in current or current[key].input_hash != finding.input_hash
            ):
                raise ValueError(f"subject changed since arbitration: {key}")
            actions.append(
                {
                    "subject_type": finding.subject_type,
                    "subject_id": finding.subject_id,
                    "action": "already_rejected" if already_applied else "reject",
                    "input_hash": finding.input_hash,
                }
            )
            if not apply or already_applied:
                continue
            note = f"Dual-model arbitration {run_code}: {finding.reason_code}. {finding.rationale}"
            now = datetime.now(UTC)
            if isinstance(row, MappingCandidate):
                row.candidate_status = "rejected"
                row.review_status = "rejected"
                session.add(
                    MappingReview(
                        mapping_candidate_id=row.id,
                        review_status="rejected",
                        reviewer=reviewer,
                        reviewed_at=now,
                        review_notes=note,
                        created_at=now,
                    )
                )
            else:
                row.review_status = "rejected"
                session.add(
                    DecisionReview(
                        candidate_result_id=row.id,
                        reviewer=reviewer,
                        reviewed_at=now,
                        decision="rejected",
                        notes=note,
                    )
                )
        summary = {
            "arbitration_run_code": run_code,
            "actions": actions,
            "customer_eligibility_granted": False,
            "applied": apply,
        }
        if apply:
            session.commit()
    if apply:
        report_dir = REPORT_ROOT / run_code
        report_dir.mkdir(parents=True, exist_ok=True)
        report_path = report_dir / "validation_results.json"
        if not report_path.exists():
            report_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
        summary["report_path"] = str(report_path)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--arbitration-run-code", required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    try:
        result = apply_actions(args.arbitration_run_code, apply=args.apply)
    except ValueError as exc:
        print(json.dumps({"valid": False, "error": str(exc)}, indent=2))
        return 1
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
