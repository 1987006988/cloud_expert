from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from cloud_expert.database.base import Base, IDMixin, ReprMixin, TableNameMixin
from cloud_expert.database.enums import (
    EvidenceOutputLevel,
    EvidencePackageRunStatus,
    EvidencePackageType,
    EvidenceReliabilityLevel,
    EvidenceStatus,
    FreshnessStatus,
    ReviewStatus,
    sql_in_values,
)

if TYPE_CHECKING:
    from cloud_expert.database.models.canonical import (
        CanonicalFieldDefinition,
        ComparabilityAssessment,
        NormalizedSpecification,
    )
    from cloud_expert.database.models.mapping import MappingCandidate
    from cloud_expert.database.models.snapshot import SnapshotRecord
    from cloud_expert.database.models.source import Evidence


class EvidencePackage(IDMixin, TableNameMixin, ReprMixin, Base):
    __table_args__ = (
        UniqueConstraint("package_code", "package_version", name="uq_evidence_package_version"),
        CheckConstraint(
            f"package_type IN ({sql_in_values(EvidencePackageType.values())})",
            name="evidence_package_type",
        ),
        CheckConstraint(
            f"freshness_status IN ({sql_in_values(FreshnessStatus.values())})",
            name="evidence_package_freshness",
        ),
        CheckConstraint(
            f"review_status IN ({sql_in_values(ReviewStatus.values())})",
            name="evidence_package_review_status",
        ),
        CheckConstraint(
            f"output_level IN ({sql_in_values(EvidenceOutputLevel.values())})",
            name="evidence_package_output_level",
        ),
        CheckConstraint(
            "evidence_completeness IS NULL OR "
            "(evidence_completeness >= 0 AND evidence_completeness <= 1)",
            name="evidence_package_completeness",
        ),
    )

    package_code: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    package_version: Mapped[str] = mapped_column(String(64), nullable=False)
    package_type: Mapped[str] = mapped_column(String(64), nullable=False)
    market_mode: Mapped[str] = mapped_column(String(64), nullable=False)
    source_entity_type: Mapped[str] = mapped_column(String(64), nullable=False)
    source_entity_id: Mapped[int] = mapped_column(nullable=False, index=True)
    target_entity_type: Mapped[str] = mapped_column(String(64), nullable=False)
    target_entity_id: Mapped[int] = mapped_column(nullable=False, index=True)
    mapping_candidate_id: Mapped[int] = mapped_column(
        ForeignKey("mapping_candidate.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    rule_set_version: Mapped[str] = mapped_column(String(64), nullable=False)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    freshness_status: Mapped[str] = mapped_column(String(64), nullable=False)
    evidence_completeness: Mapped[Decimal | None] = mapped_column(Numeric(5, 4))
    review_status: Mapped[str] = mapped_column(String(64), nullable=False)
    output_level: Mapped[str] = mapped_column(String(64), nullable=False)
    customer_eligible: Mapped[bool] = mapped_column(nullable=False, default=False)
    content_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    superseded_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("evidence_package.id", ondelete="SET NULL"),
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    mapping_candidate: Mapped[MappingCandidate] = relationship()
    superseded_by: Mapped[EvidencePackage | None] = relationship(remote_side="EvidencePackage.id")
    items: Mapped[list[EvidencePackageItem]] = relationship(back_populates="package")


class EvidencePackageItem(IDMixin, TableNameMixin, ReprMixin, Base):
    __table_args__ = (
        UniqueConstraint(
            "package_id",
            "canonical_field_id",
            "source_value_id",
            "target_value_id",
            "display_order",
            name="uq_evidence_package_item_identity",
        ),
        CheckConstraint(
            f"freshness_status IN ({sql_in_values(FreshnessStatus.values())})",
            name="evidence_package_item_freshness",
        ),
    )

    package_id: Mapped[int] = mapped_column(
        ForeignKey("evidence_package.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    canonical_field_id: Mapped[int | None] = mapped_column(
        ForeignKey("canonical_field_definition.id", ondelete="RESTRICT"),
        index=True,
    )
    source_value_id: Mapped[int | None] = mapped_column(
        ForeignKey("normalized_specification.id", ondelete="RESTRICT"),
        index=True,
    )
    target_value_id: Mapped[int | None] = mapped_column(
        ForeignKey("normalized_specification.id", ondelete="RESTRICT"),
        index=True,
    )
    comparability_assessment_id: Mapped[int | None] = mapped_column(
        ForeignKey("comparability_assessment.id", ondelete="SET NULL"),
        index=True,
    )
    source_evidence_id: Mapped[int | None] = mapped_column(
        ForeignKey("evidence.id", ondelete="RESTRICT"),
        index=True,
    )
    target_evidence_id: Mapped[int | None] = mapped_column(
        ForeignKey("evidence.id", ondelete="RESTRICT"),
        index=True,
    )
    source_reference_code: Mapped[str | None] = mapped_column(String(160))
    target_reference_code: Mapped[str | None] = mapped_column(String(160))
    comparison_status: Mapped[str] = mapped_column(String(64), nullable=False)
    matched_status: Mapped[str] = mapped_column(String(64), nullable=False)
    scope_status: Mapped[str] = mapped_column(String(64), nullable=False)
    qualifier_status: Mapped[str] = mapped_column(String(64), nullable=False)
    freshness_status: Mapped[str] = mapped_column(String(64), nullable=False)
    conflict_status: Mapped[str] = mapped_column(String(64), nullable=False)
    blocking_reason: Mapped[str | None] = mapped_column(Text)
    display_order: Mapped[int] = mapped_column(nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    package: Mapped[EvidencePackage] = relationship(back_populates="items")
    canonical_field: Mapped[CanonicalFieldDefinition | None] = relationship()
    source_value: Mapped[NormalizedSpecification | None] = relationship(
        foreign_keys=[source_value_id]
    )
    target_value: Mapped[NormalizedSpecification | None] = relationship(
        foreign_keys=[target_value_id]
    )
    comparability_assessment: Mapped[ComparabilityAssessment | None] = relationship()
    source_evidence: Mapped[Evidence | None] = relationship(foreign_keys=[source_evidence_id])
    target_evidence: Mapped[Evidence | None] = relationship(foreign_keys=[target_evidence_id])


class EvidenceReference(IDMixin, TableNameMixin, ReprMixin, Base):
    __table_args__ = (
        UniqueConstraint("reference_code", name="uq_evidence_reference_code"),
        UniqueConstraint("evidence_id", name="uq_evidence_reference_evidence"),
        CheckConstraint(
            f"reliability_level IN ({sql_in_values(EvidenceReliabilityLevel.values())})",
            name="evidence_reference_reliability",
        ),
        CheckConstraint(
            f"evidence_status IN ({sql_in_values(EvidenceStatus.values())})",
            name="evidence_reference_status",
        ),
        CheckConstraint(
            f"freshness_status IN ({sql_in_values(FreshnessStatus.values())})",
            name="evidence_reference_freshness",
        ),
    )

    reference_code: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    evidence_id: Mapped[int] = mapped_column(
        ForeignKey("evidence.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    snapshot_id: Mapped[int | None] = mapped_column(
        ForeignKey("snapshot_record.id", ondelete="SET NULL"),
        index=True,
    )
    content_hash: Mapped[str | None] = mapped_column(String(128))
    locator: Mapped[str] = mapped_column(String(512), nullable=False)
    excerpt: Mapped[str] = mapped_column(Text, nullable=False)
    source_title: Mapped[str] = mapped_column(String(256), nullable=False)
    source_url: Mapped[str] = mapped_column(String(1024), nullable=False)
    captured_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reliability_level: Mapped[str] = mapped_column(String(64), nullable=False)
    evidence_status: Mapped[str] = mapped_column(String(64), nullable=False)
    freshness_status: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    evidence: Mapped[Evidence] = relationship()
    snapshot: Mapped[SnapshotRecord | None] = relationship()


class EvidencePackageRun(IDMixin, TableNameMixin, ReprMixin, Base):
    __table_args__ = (
        UniqueConstraint("run_code", name="uq_evidence_package_run_code"),
        CheckConstraint(
            f"package_type IN ({sql_in_values(EvidencePackageType.values())})",
            name="evidence_package_run_type",
        ),
        CheckConstraint(
            f"status IN ({sql_in_values(EvidencePackageRunStatus.values())})",
            name="evidence_package_run_status",
        ),
    )

    run_code: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    package_type: Mapped[str] = mapped_column(String(64), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(64), nullable=False)
    candidate_count: Mapped[int] = mapped_column(nullable=False, default=0)
    package_count: Mapped[int] = mapped_column(nullable=False, default=0)
    item_count: Mapped[int] = mapped_column(nullable=False, default=0)
    conflict_count: Mapped[int] = mapped_column(nullable=False, default=0)
    missing_evidence_count: Mapped[int] = mapped_column(nullable=False, default=0)
    stale_count: Mapped[int] = mapped_column(nullable=False, default=0)
    error_count: Mapped[int] = mapped_column(nullable=False, default=0)
    generator_version: Mapped[str] = mapped_column(String(64), nullable=False)
