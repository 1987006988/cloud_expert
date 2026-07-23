from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from cloud_expert.database.models.evidence_package import (
    EvidencePackage,
    EvidencePackageItem,
    EvidenceReference,
)


def validate_evidence_references(session: Session) -> dict[str, Any]:
    references = session.scalar(select(func.count()).select_from(EvidenceReference)) or 0
    missing_snapshot = (
        session.scalar(
            select(func.count())
            .select_from(EvidenceReference)
            .where(EvidenceReference.snapshot_id.is_(None))
        )
        or 0
    )
    duplicate_codes = session.execute(
        select(EvidenceReference.reference_code, func.count(EvidenceReference.id))
        .group_by(EvidenceReference.reference_code)
        .having(func.count(EvidenceReference.id) > 1)
    ).all()
    return {
        "references": references,
        "missing_snapshot": missing_snapshot,
        "duplicate_reference_codes": len(duplicate_codes),
        "valid": references > 0 and missing_snapshot == 0 and not duplicate_codes,
    }


def validate_evidence_package_idempotency(
    before: dict[str, int], after: dict[str, int]
) -> dict[str, Any]:
    errors = [key for key, value in before.items() if after.get(key) != value]
    return {"before": before, "after": after, "errors": errors, "valid": not errors}


def evidence_package_counts(session: Session) -> dict[str, int]:
    return {
        "packages": session.scalar(select(func.count()).select_from(EvidencePackage)) or 0,
        "items": session.scalar(select(func.count()).select_from(EvidencePackageItem)) or 0,
        "references": session.scalar(select(func.count()).select_from(EvidenceReference)) or 0,
    }


def customer_output_eligibility(session: Session, package_code: str) -> dict[str, Any]:
    package = session.scalar(
        select(EvidencePackage).where(EvidencePackage.package_code == package_code)
    )
    if package is None:
        return {"package_code": package_code, "exists": False, "customer_eligible": False}
    return {
        "package_code": package.package_code,
        "exists": True,
        "customer_eligible": package.customer_eligible,
        "review_status": package.review_status,
        "output_level": package.output_level,
        "reason": (
            "eligible"
            if package.customer_eligible
            else "mapping or evidence remains pending review or has completeness blockers"
        ),
    }


def customer_output_eligibility_summary(session: Session) -> dict[str, Any]:
    total = session.scalar(select(func.count()).select_from(EvidencePackage)) or 0
    eligible = (
        session.scalar(
            select(func.count())
            .select_from(EvidencePackage)
            .where(EvidencePackage.customer_eligible.is_(True))
        )
        or 0
    )
    internal_only = total - eligible
    pending_review = (
        session.scalar(
            select(func.count())
            .select_from(EvidencePackage)
            .where(EvidencePackage.review_status == "pending_review")
        )
        or 0
    )
    return {
        "packages": total,
        "customer_eligible": eligible,
        "internal_only": internal_only,
        "pending_review": pending_review,
        "valid": eligible == 0 and internal_only == total,
    }
