from __future__ import annotations

import json
from typing import Any

import _bootstrap  # noqa: F401
from sqlalchemy import func, or_, select
from sqlalchemy.orm import aliased

from cloud_expert.database.enums import MappingCandidateStatus, ReviewStatus
from cloud_expert.database.models.canonical import NormalizedSpecification
from cloud_expert.database.models.evidence_package import EvidencePackage, EvidencePackageItem
from cloud_expert.database.models.mapping import MappingCandidate
from cloud_expert.database.session import SessionLocal


def validate_active_evidence_packages() -> dict[str, Any]:
    source = aliased(NormalizedSpecification)
    target = aliased(NormalizedSpecification)
    with SessionLocal() as session:
        active = (
            session.scalar(
                select(func.count())
                .select_from(EvidencePackage)
                .join(MappingCandidate, EvidencePackage.mapping_candidate_id == MappingCandidate.id)
                .where(
                    EvidencePackage.superseded_by_id.is_(None),
                    MappingCandidate.candidate_status.not_in(
                        [
                            MappingCandidateStatus.REJECTED.value,
                            MappingCandidateStatus.SUPERSEDED.value,
                        ]
                    ),
                )
            )
            or 0
        )
        rejected_links = (
            session.scalar(
                select(func.count())
                .select_from(EvidencePackageItem)
                .join(EvidencePackage, EvidencePackageItem.package_id == EvidencePackage.id)
                .join(MappingCandidate, EvidencePackage.mapping_candidate_id == MappingCandidate.id)
                .outerjoin(source, EvidencePackageItem.source_value_id == source.id)
                .outerjoin(target, EvidencePackageItem.target_value_id == target.id)
                .where(
                    EvidencePackage.superseded_by_id.is_(None),
                    MappingCandidate.candidate_status.not_in(
                        [
                            MappingCandidateStatus.REJECTED.value,
                            MappingCandidateStatus.SUPERSEDED.value,
                        ]
                    ),
                    or_(
                        source.review_status == ReviewStatus.REJECTED.value,
                        target.review_status == ReviewStatus.REJECTED.value,
                    ),
                )
            )
            or 0
        )
        full_completeness_with_missing_item = (
            session.scalar(
                select(func.count())
                .select_from(EvidencePackageItem)
                .join(EvidencePackage, EvidencePackageItem.package_id == EvidencePackage.id)
                .join(MappingCandidate, EvidencePackage.mapping_candidate_id == MappingCandidate.id)
                .where(
                    EvidencePackage.superseded_by_id.is_(None),
                    MappingCandidate.candidate_status.not_in(
                        [
                            MappingCandidateStatus.REJECTED.value,
                            MappingCandidateStatus.SUPERSEDED.value,
                        ]
                    ),
                    EvidencePackage.evidence_completeness == 1,
                    or_(
                        EvidencePackageItem.source_evidence_id.is_(None),
                        EvidencePackageItem.target_evidence_id.is_(None),
                        EvidencePackageItem.scope_status == "not_evaluated",
                        EvidencePackageItem.qualifier_status == "not_evaluated",
                    ),
                )
            )
            or 0
        )
    return {
        "active_packages": active,
        "active_rejected_value_links": rejected_links,
        "full_completeness_with_missing_item": full_completeness_with_missing_item,
        "valid": active > 0 and rejected_links == 0 and full_completeness_with_missing_item == 0,
    }


def main() -> int:
    result = validate_active_evidence_packages()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
