from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import _bootstrap  # noqa: F401
from check_week09_gate import check_week09_gate
from check_week10_gate import check_week10_gate
from sqlalchemy import func, select

from cloud_expert.database.enums import (
    DecisionOutputLevel,
    DecisionReviewStatus,
    EvidenceOutputLevel,
    ReviewStatus,
    TCOCompletenessStatus,
)
from cloud_expert.database.models.canonical import CanonicalFieldDefinition, NormalizedSpecification
from cloud_expert.database.models.decision import CandidateDecisionResult, DecisionReview
from cloud_expert.database.models.evidence_package import EvidencePackage
from cloud_expert.database.models.mapping import MappingCandidate
from cloud_expert.database.models.product import Product
from cloud_expert.database.models.product_extension import ProductSLA
from cloud_expert.database.models.provider import Provider
from cloud_expert.database.models.region import AvailabilityZone
from cloud_expert.database.models.review import (
    HumanReviewDecision,
    HumanReviewImportBatch,
    ModelReviewFinding,
    ModelReviewRun,
)
from cloud_expert.database.models.tco import TCOResult
from cloud_expert.database.session import SessionLocal

REPORT_DIR = Path("reports") / "week11_gate"
REQUIRED_DOCS = [
    "docs/MAPPING_REVIEW_GUIDE.md",
    "docs/DECISION_REVIEW_GUIDE.md",
    "docs/CUSTOMER_OUTPUT_ELIGIBILITY.md",
    "docs/DECISION_OUTPUT_ELIGIBILITY.md",
    "docs/COMPARISON_REPORT_POLICY.md",
]


def _count_active_bad_aws_memory() -> int:
    with SessionLocal() as session:
        provider = session.scalar(select(Provider).where(Provider.code == "aws"))
        product = (
            None
            if provider is None
            else session.scalar(
                select(Product).where(Product.provider_id == provider.id, Product.code == "ec2")
            )
        )
        field = session.scalar(
            select(CanonicalFieldDefinition).where(
                CanonicalFieldDefinition.code == "compute.memory.capacity_gib"
            )
        )
        if product is None or field is None:
            return 0
        return (
            session.scalar(
                select(func.count())
                .select_from(NormalizedSpecification)
                .where(
                    NormalizedSpecification.product_id == product.id,
                    NormalizedSpecification.canonical_field_id == field.id,
                    NormalizedSpecification.review_status != ReviewStatus.REJECTED.value,
                    NormalizedSpecification.numeric_value.is_(None),
                )
            )
            or 0
        )


def _readiness() -> dict[str, Any]:
    with SessionLocal() as session:
        review_batches = (
            session.scalar(select(func.count()).select_from(HumanReviewImportBatch)) or 0
        )
        review_decisions = (
            session.scalar(select(func.count()).select_from(HumanReviewDecision)) or 0
        )
        model_review_runs = session.scalar(select(func.count()).select_from(ModelReviewRun)) or 0
        model_review_findings = (
            session.scalar(select(func.count()).select_from(ModelReviewFinding)) or 0
        )
        decision_counts: dict[str, int] = {
            str(status): int(count)
            for status, count in session.execute(
                select(HumanReviewDecision.reviewer_decision, func.count())
                .select_from(HumanReviewDecision)
                .group_by(HumanReviewDecision.reviewer_decision)
            ).tuples()
        }
        mapping_candidates = session.scalar(select(func.count()).select_from(MappingCandidate)) or 0
        human_reviewed_mappings = (
            session.scalar(
                select(func.count())
                .select_from(MappingCandidate)
                .where(MappingCandidate.review_status == ReviewStatus.HUMAN_REVIEWED.value)
            )
            or 0
        )
        evidence_packages = session.scalar(select(func.count()).select_from(EvidencePackage)) or 0
        customer_evidence = (
            session.scalar(
                select(func.count())
                .select_from(EvidencePackage)
                .where(
                    EvidencePackage.output_level == EvidenceOutputLevel.CUSTOMER_ELIGIBLE.value,
                    EvidencePackage.customer_eligible.is_(True),
                )
            )
            or 0
        )
        complete_tco = (
            session.scalar(
                select(func.count())
                .select_from(TCOResult)
                .where(TCOResult.completeness_status == TCOCompletenessStatus.COMPLETE.value)
            )
            or 0
        )
        decision_reviews = session.scalar(select(func.count()).select_from(DecisionReview)) or 0
        internally_approved = (
            session.scalar(
                select(func.count())
                .select_from(CandidateDecisionResult)
                .where(
                    CandidateDecisionResult.review_status
                    == DecisionReviewStatus.INTERNALLY_APPROVED.value
                )
            )
            or 0
        )
        customer_decisions = (
            session.scalar(
                select(func.count())
                .select_from(CandidateDecisionResult)
                .where(
                    CandidateDecisionResult.output_level
                    == DecisionOutputLevel.CUSTOMER_ELIGIBLE_CANDIDATE.value,
                    CandidateDecisionResult.customer_eligible.is_(True),
                )
            )
            or 0
        )
        zone_name_equals_code = (
            session.scalar(
                select(func.count())
                .select_from(AvailabilityZone)
                .where(AvailabilityZone.zone_name == AvailabilityZone.zone_code)
            )
            or 0
        )
        rejected_sla = (
            session.scalar(
                select(func.count())
                .select_from(ProductSLA)
                .where(ProductSLA.review_status == ReviewStatus.REJECTED.value)
            )
            or 0
        )
    return {
        "review_batches": review_batches,
        "review_decisions": review_decisions,
        "model_review_runs": model_review_runs,
        "model_review_findings": model_review_findings,
        "review_decision_counts": decision_counts,
        "mapping_candidates": mapping_candidates,
        "human_reviewed_mappings": human_reviewed_mappings,
        "evidence_packages": evidence_packages,
        "customer_eligible_evidence_packages": customer_evidence,
        "complete_tco_results": complete_tco,
        "decision_reviews": decision_reviews,
        "internally_approved_decision_results": internally_approved,
        "customer_eligible_decision_results": customer_decisions,
        "sales_output_ready_scenarios": min(
            human_reviewed_mappings,
            customer_evidence,
            complete_tco,
            internally_approved,
            customer_decisions,
        ),
        "active_bad_aws_memory_records": _count_active_bad_aws_memory(),
        "aliyun_zone_name_equals_code": zone_name_equals_code,
        "rejected_sla_records": rejected_sla,
    }


def check_week11_gate() -> dict[str, Any]:
    week9 = check_week09_gate()
    week10 = check_week10_gate()
    readiness = _readiness()
    missing_docs = [doc for doc in REQUIRED_DOCS if not Path(doc).exists()]
    blockers: list[str] = []
    if week9["verdict"] != "GO":
        blockers.append("W11-B001-week9-gate")
    if week10["verdict"] != "GO":
        blockers.append("W11-B002-week10-gate")
    if readiness["review_batches"] == 0 or readiness["review_decisions"] == 0:
        blockers.append("W11-B003-review-import")
    if readiness["active_bad_aws_memory_records"] > 0:
        blockers.append("W11-B004-aws-memory-remediation")
    if readiness["aliyun_zone_name_equals_code"] > 0:
        blockers.append("W11-B005-aliyun-zone-remediation")
    if readiness["human_reviewed_mappings"] == 0:
        blockers.append("W11-B007-human-reviewed-mapping")
    if readiness["customer_eligible_evidence_packages"] == 0:
        blockers.append("W11-B008-customer-evidence")
    if readiness["complete_tco_results"] == 0:
        blockers.append("W11-B009-complete-tco")
    if readiness["decision_reviews"] == 0 or readiness["internally_approved_decision_results"] == 0:
        blockers.append("W11-B010-decision-review")
    if readiness["customer_eligible_decision_results"] == 0:
        blockers.append("W11-B011-customer-decision-output")
    if missing_docs:
        blockers.append("W11-B012-required-docs")
    return {
        "gate": "WEEK11_GATE",
        "verdict": "GO" if not blockers else "NO-GO",
        "week9_gate": week9["verdict"],
        "week10_gate": week10["verdict"],
        "readiness": readiness,
        "missing_required_docs": missing_docs,
        "blocking_items": blockers,
        "sales_output_generated": False,
        "objection_handling_generated": False,
        "poc_recommendations_generated": False,
    }


def write_gate_reports(result: dict[str, Any]) -> None:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    (REPORT_DIR / "validation_results.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    readiness = result["readiness"]
    (REPORT_DIR / "gate_summary.md").write_text(
        "\n".join(
            [
                "# Week 11 Gate Summary",
                "",
                f"- Verdict: `{result['verdict']}`",
                f"- Week9 Gate: `{result['week9_gate']}`",
                f"- Week10 Gate: `{result['week10_gate']}`",
                f"- Review decisions imported: {readiness['review_decisions']}",
                f"- Sales-output-ready scenarios: {readiness['sales_output_ready_scenarios']}",
                "",
            ]
        ),
        encoding="utf-8",
    )
    (REPORT_DIR / "unresolved_blockers.md").write_text(
        "# Unresolved Blockers\n\n"
        + ("\n".join(f"- `{item}`" for item in result["blocking_items"]) or "None\n"),
        encoding="utf-8",
    )
    (REPORT_DIR / "review_import_status.md").write_text(
        "# Review Import Status\n\n"
        + json.dumps(
            {
                "review_batches": readiness["review_batches"],
                "review_decisions": readiness["review_decisions"],
                "review_decision_counts": readiness["review_decision_counts"],
                "model_review_runs": readiness["model_review_runs"],
                "model_review_findings": readiness["model_review_findings"],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    (REPORT_DIR / "decision_readiness.md").write_text(
        "# Decision Readiness\n\n"
        + json.dumps(
            {
                "decision_reviews": readiness["decision_reviews"],
                "internally_approved_decision_results": readiness[
                    "internally_approved_decision_results"
                ],
                "customer_eligible_decision_results": readiness[
                    "customer_eligible_decision_results"
                ],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    (REPORT_DIR / "customer_output_readiness.md").write_text(
        "# Customer Output Readiness\n\n" + json.dumps(readiness, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (REPORT_DIR / "recommended_next_actions.md").write_text(
        "# Recommended Next Actions\n\n"
        + (
            "- Complete the listed blockers before generating Week 11 sales output.\n"
            if result["blocking_items"]
            else "- Week 11 gate is open for evidence-constrained sales output.\n"
        ),
        encoding="utf-8",
    )


def main() -> int:
    result = check_week11_gate()
    write_gate_reports(result)
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return 0 if result["verdict"] == "GO" else 1


if __name__ == "__main__":
    raise SystemExit(main())
