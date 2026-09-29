from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import Select, create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker

from cloud_expert.config.settings import get_settings
from cloud_expert.database.enums import (
    AuthorityLevel,
    FieldComparisonStatus,
    MappingCandidateStatus,
    MappingEvidenceRole,
    MappingLevel,
    MappingRelationshipType,
    ReviewStatus,
    RuleSetStatus,
)
from cloud_expert.database.models.canonical import CanonicalFieldDefinition, NormalizedSpecification
from cloud_expert.database.models.mapping import (
    MappingCandidate,
    MappingCandidateEvidence,
    MappingFieldComparison,
    MappingRuleSet,
)
from cloud_expert.database.models.parsing import ParsedFieldCandidate
from cloud_expert.database.models.product import SKU, Product
from cloud_expert.database.models.product_extension import ProductFamily, ServiceTier
from cloud_expert.database.models.provider import Provider
from cloud_expert.database.models.snapshot import SnapshotRecord
from cloud_expert.database.models.source import SourceDocument
from cloud_expert.mapping.rules import (
    RULE_VERSION,
    classify_family,
    classify_tier,
    relationship_for_score,
    score_cpu_memory,
)
from cloud_expert.normalization.evidence_validity import (
    HashCache,
    current_normalized_statement,
    normalized_evidence_valid,
)

MARKET_RULE_VERSION = "2026.09.week12.market.v1"
CURRENT_SKU_RULE_VERSION = "2026.09.week14.current-evidence.v2"


@dataclass
class MappingGenerationResult:
    rule_sets: int = 0
    product_candidates: int = 0
    family_candidates: int = 0
    sku_candidates: int = 0
    service_tier_candidates: int = 0
    field_comparisons: int = 0
    evidence_links: int = 0
    not_comparable: int = 0
    pending_review: int = 0
    errors: list[str] = field(default_factory=list)

    @property
    def total_candidates(self) -> int:
        return (
            self.product_candidates
            + self.family_candidates
            + self.sku_candidates
            + self.service_tier_candidates
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "rule_sets": self.rule_sets,
            "product_candidates": self.product_candidates,
            "family_candidates": self.family_candidates,
            "sku_candidates": self.sku_candidates,
            "service_tier_candidates": self.service_tier_candidates,
            "field_comparisons": self.field_comparisons,
            "evidence_links": self.evidence_links,
            "not_comparable": self.not_comparable,
            "pending_review": self.pending_review,
            "total_candidates": self.total_candidates,
            "errors": self.errors,
        }


def make_session(database_url: str | None = None) -> Session:
    url = database_url or get_settings().database_url
    connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
    engine = create_engine(url, future=True, connect_args=connect_args)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)()


def generate_all_mapping_candidates(session: Session) -> MappingGenerationResult:
    result = MappingGenerationResult()
    now = datetime.now(UTC)
    rule_sets = _ensure_rule_sets(session, now)
    result.rule_sets = len(rule_sets)
    if not rule_sets:
        return result

    result.product_candidates += _generate_product_candidates(session, rule_sets, now)
    result.family_candidates += _generate_family_candidates(session, rule_sets, now)
    result.sku_candidates += _generate_sku_candidates(session, rule_sets, now)
    result.service_tier_candidates += _generate_service_tier_candidates(session, rule_sets, now)
    result.field_comparisons = _count(session, MappingFieldComparison)
    result.evidence_links = _count(session, MappingCandidateEvidence)
    result.not_comparable = (
        session.scalar(
            select(func.count())
            .select_from(MappingCandidate)
            .where(MappingCandidate.candidate_status == MappingCandidateStatus.NOT_COMPARABLE.value)
        )
        or 0
    )
    result.pending_review = (
        session.scalar(
            select(func.count())
            .select_from(MappingCandidate)
            .where(MappingCandidate.review_status == ReviewStatus.PENDING_REVIEW.value)
        )
        or 0
    )
    session.commit()
    return result


def _count(session: Session, model: type[Any]) -> int:
    return session.scalar(select(func.count()).select_from(model)) or 0


def _ensure_rule_sets(session: Session, now: datetime) -> dict[str, MappingRuleSet]:
    base_definitions = [
        ("week07_product", MappingLevel.PRODUCT.value, "all", "cross_market"),
        ("week07_compute_family", MappingLevel.PRODUCT_FAMILY.value, "compute", "cross_market"),
        ("week07_compute_sku", MappingLevel.SKU.value, "compute", "cross_market"),
        (
            "week07_object_storage_tier",
            MappingLevel.SERVICE_TIER.value,
            "object_storage",
            "cross_market",
        ),
    ]
    definitions = list(base_definitions)
    definitions.extend(
        (f"{code}_{mode}", level, category, mode)
        for code, level, category, _ in base_definitions
        for mode in ("domestic", "international")
    )
    result: dict[str, MappingRuleSet] = {}
    for code, level, category, market_mode in definitions:
        version = RULE_VERSION if market_mode == "cross_market" else MARKET_RULE_VERSION
        if level == MappingLevel.SKU.value:
            version = CURRENT_SKU_RULE_VERSION
        existing = session.scalar(
            select(MappingRuleSet).where(
                MappingRuleSet.rule_set_code == code,
                MappingRuleSet.rule_set_version == version,
            )
        )
        if existing is None:
            existing = MappingRuleSet(
                rule_set_code=code,
                rule_set_version=version,
                mapping_level=level,
                category=category,
                market_mode=market_mode,
                description=f"Deterministic Week 7 {level} mapping rules.",
                required_fields=_required_fields_for(level),
                optional_fields=_optional_fields_for(level),
                exclusion_rules=[
                    {
                        "rule_id": "no_auto_approval",
                        "description": "automatic candidates stay pending",
                    },
                    {"rule_id": "evidence_required", "description": "candidate must link evidence"},
                    {
                        "rule_id": "scope_qualifier_visible",
                        "description": "scope and qualifier are preserved",
                    },
                ],
                scoring_config={"rule_version": version, "max_targets_per_source": 5},
                status=RuleSetStatus.ACTIVE.value,
                effective_from=now,
            )
            session.add(existing)
            session.flush()
        result[code] = existing
    return result


def _market_rule_set(
    rule_sets: dict[str, MappingRuleSet], code: str, source: Product, target: Product
) -> MappingRuleSet:
    if source.market_mode == target.market_mode:
        return rule_sets[f"{code}_{source.market_mode}"]
    return rule_sets[code]


def _required_fields_for(level: str) -> list[str]:
    if level == MappingLevel.SKU.value:
        return ["compute.cpu.vcpu_count", "compute.memory.capacity_gib"]
    if level == MappingLevel.SERVICE_TIER.value:
        return ["access_pattern", "redundancy_scope"]
    if level == MappingLevel.PRODUCT_FAMILY.value:
        return ["family_category", "virtualization_shape"]
    return ["product_category", "official_positioning_evidence"]


def _optional_fields_for(level: str) -> list[str]:
    if level == MappingLevel.SKU.value:
        return ["architecture", "network", "local_disk", "gpu", "region"]
    if level == MappingLevel.SERVICE_TIER.value:
        return ["minimum_storage_duration_days", "retrieval_characteristics", "durability"]
    return ["lifecycle_status", "market_mode", "availability"]


def _generate_product_candidates(
    session: Session, rule_sets: dict[str, MappingRuleSet], now: datetime
) -> int:
    pairs = [
        ("huawei_cloud", "ecs", "aws", "ec2"),
        ("huawei_cloud", "ecs", "aliyun", "ecs"),
        ("huawei_cloud", "obs", "aws", "s3"),
        ("huawei_cloud", "obs", "aliyun", "oss"),
    ]
    created = 0
    for source_provider, source_product, target_provider, target_product in pairs:
        source = _product(session, source_provider, source_product)
        target = _product(session, target_provider, target_product)
        if source is None or target is None:
            continue
        rule_set = _market_rule_set(rule_sets, "week07_product", source, target)
        source_evidence = _first_product_evidence(session, source.id)
        target_evidence = _first_product_evidence(session, target.id)
        candidate = _upsert_candidate(
            session=session,
            rule_set=rule_set,
            mapping_level=MappingLevel.PRODUCT.value,
            source_provider_id=source.provider_id,
            source_entity_type="product",
            source_entity_id=source.id,
            target_provider_id=target.provider_id,
            target_entity_type="product",
            target_entity_id=target.id,
            relationship_type=MappingRelationshipType.SAME_SERVICE_CLASS.value,
            candidate_status=MappingCandidateStatus.CANDIDATE.value,
            raw_score=Decimal("90.0000"),
            normalized_score=Decimal("0.9000"),
            confidence=Decimal("0.8500"),
            blocking_reasons=[]
            if source_evidence and target_evidence
            else ["missing_product_evidence"],
            conditions=["product-level mapping does not imply SKU equivalence"],
            explanation=(
                f"{source.display_name} and {target.display_name} share product category "
                f"{source.category.code}; SKU, region, network, storage and billing facts require "
                "separate comparison."
            ),
            now=now,
        )
        if source_evidence:
            _link_evidence(
                session,
                candidate,
                source_evidence,
                MappingEvidenceRole.CATEGORY_POSITIONING.value,
                now,
            )
        if target_evidence:
            _link_evidence(
                session,
                candidate,
                target_evidence,
                MappingEvidenceRole.CATEGORY_POSITIONING.value,
                now,
            )
        created += 1
    return created


def _generate_family_candidates(
    session: Session, rule_sets: dict[str, MappingRuleSet], now: datetime
) -> int:
    sources = _families(session, "huawei_cloud", "ecs")
    targets_by_provider = {
        "aws": _families(session, "aws", "ec2"),
        "aliyun": _families(session, "aliyun", "ecs"),
    }
    created = 0
    for source in sources:
        source_tag = classify_family(source.family_code, source.family_name)
        for provider_code, targets in targets_by_provider.items():
            matching = [
                target
                for target in targets
                if classify_family(target.family_code, target.family_name).category
                == source_tag.category
            ][:5]
            if not matching and targets:
                matching = targets[:1]
            for target in matching:
                rule_set = _market_rule_set(
                    rule_sets, "week07_compute_family", source.product, target.product
                )
                target_tag = classify_family(target.family_code, target.family_name)
                blockers: list[str] = []
                conditions = [
                    f"source_family_tag={source_tag.category}",
                    f"target_family_tag={target_tag.category}",
                ]
                if source_tag.category != target_tag.category:
                    blockers.append("family_category_mismatch")
                if source_tag.bare_metal != target_tag.bare_metal:
                    blockers.append("bare_metal_shape_mismatch")
                if source_tag.burstable != target_tag.burstable:
                    conditions.append("burstable_shape_requires_review")
                score = Decimal("0.8200") if not blockers else Decimal("0.4500")
                candidate = _upsert_candidate(
                    session=session,
                    rule_set=rule_set,
                    mapping_level=MappingLevel.PRODUCT_FAMILY.value,
                    source_provider_id=source.product.provider_id,
                    source_entity_type="product_family",
                    source_entity_id=source.id,
                    target_provider_id=target.product.provider_id,
                    target_entity_type="product_family",
                    target_entity_id=target.id,
                    relationship_type=(
                        MappingRelationshipType.CLOSE_ALTERNATIVE.value
                        if not blockers
                        else MappingRelationshipType.PARTIAL_OVERLAP.value
                    ),
                    candidate_status=(
                        MappingCandidateStatus.CANDIDATE.value
                        if not blockers
                        else MappingCandidateStatus.NOT_COMPARABLE.value
                    ),
                    raw_score=score * Decimal("100"),
                    normalized_score=score,
                    confidence=Decimal("0.7000") if not blockers else Decimal("0.4000"),
                    blocking_reasons=blockers,
                    conditions=conditions,
                    explanation=(
                        f"Family candidate generated from deterministic category tags, not name-only "
                        f"matching: {source.family_code} -> {target.family_code} ({provider_code})."
                    ),
                    now=now,
                )
                if source.evidence_id:
                    _link_evidence(
                        session,
                        candidate,
                        source.evidence_id,
                        MappingEvidenceRole.SOURCE_FIELD.value,
                        now,
                    )
                if target.evidence_id:
                    _link_evidence(
                        session,
                        candidate,
                        target.evidence_id,
                        MappingEvidenceRole.TARGET_FIELD.value,
                        now,
                    )
                created += 1
    return created


def _generate_sku_candidates(
    session: Session, rule_sets: dict[str, MappingRuleSet], now: datetime
) -> int:
    source_skus = _skus(session, "huawei_cloud", "ecs")[:80]
    target_sets = {"aws": _skus(session, "aws", "ec2"), "aliyun": _skus(session, "aliyun", "ecs")}
    all_skus = source_skus + [sku for targets in target_sets.values() for sku in targets]
    values_by_sku = _sku_values_for_skus(session, [sku.id for sku in all_skus])
    created = 0
    for source in source_skus:
        source_values = values_by_sku.get(source.id, {})
        source_vcpu = _numeric_value(source_values, "compute.cpu.vcpu_count")
        source_memory = _numeric_value(source_values, "compute.memory.capacity_gib")
        for targets in target_sets.values():
            scored: list[tuple[Decimal, SKU, list[str], list[str]]] = []
            for target in targets:
                target_values = values_by_sku.get(target.id, {})
                target_vcpu = _numeric_value(target_values, "compute.cpu.vcpu_count")
                target_memory = _numeric_value(target_values, "compute.memory.capacity_gib")
                score, blockers, conditions = score_cpu_memory(
                    source_vcpu, source_memory, target_vcpu, target_memory
                )
                source_architecture = _normalized_architecture(source.architecture)
                target_architecture = _normalized_architecture(target.architecture)
                if source_architecture != target_architecture and "unknown" not in {
                    source_architecture,
                    target_architecture,
                }:
                    conditions.append("architecture_requires_review")
                if score >= Decimal("0.7500") or blockers:
                    scored.append((score, target, blockers, conditions))
            for score, target, blockers, conditions in sorted(
                scored, key=lambda row: row[0], reverse=True
            )[:4]:
                rule_set = _market_rule_set(
                    rule_sets, "week07_compute_sku", source.product, target.product
                )
                target_values = values_by_sku.get(target.id, {})
                relationship = relationship_for_score(score, blockers)
                candidate_status = (
                    MappingCandidateStatus.CANDIDATE.value
                    if not blockers
                    else MappingCandidateStatus.NOT_COMPARABLE.value
                )
                candidate = _upsert_candidate(
                    session=session,
                    rule_set=rule_set,
                    mapping_level=MappingLevel.SKU.value,
                    source_provider_id=source.product.provider_id,
                    source_entity_type="sku",
                    source_entity_id=source.id,
                    target_provider_id=target.product.provider_id,
                    target_entity_type="sku",
                    target_entity_id=target.id,
                    relationship_type=relationship,
                    candidate_status=candidate_status,
                    raw_score=score * Decimal("100"),
                    normalized_score=score,
                    confidence=Decimal("0.7600") if not blockers else Decimal("0.3500"),
                    blocking_reasons=blockers,
                    conditions=conditions
                    or ["same vCPU and memory do not imply performance equivalence"],
                    explanation=(
                        f"SKU candidate compares normalized vCPU and memory with evidence-backed values: "
                        f"{source.provider_sku_code} -> {target.provider_sku_code}."
                    ),
                    now=now,
                )
                _add_sku_field_comparisons(session, candidate, source_values, target_values, now)
                created += 1
    return created


def _generate_service_tier_candidates(
    session: Session, rule_sets: dict[str, MappingRuleSet], now: datetime
) -> int:
    sources = _tiers(session, "huawei_cloud", "obs")
    targets_by_provider = {
        "aws": _tiers(session, "aws", "s3"),
        "aliyun": _tiers(session, "aliyun", "oss"),
    }
    created = 0
    for source in sources:
        source_tag = classify_tier(source.tier_code, source.official_name, source.access_pattern)
        for targets in targets_by_provider.values():
            for target in targets:
                rule_set = _market_rule_set(
                    rule_sets, "week07_object_storage_tier", source.product, target.product
                )
                target_tag = classify_tier(
                    target.tier_code, target.official_name, target.access_pattern
                )
                if (
                    source_tag.access_class != target_tag.access_class
                    and source_tag.access_class != "unknown"
                ):
                    continue
                blockers: list[str] = []
                conditions = [f"access_class={source_tag.access_class}"]
                if (
                    source_tag.redundancy_scope != "unknown"
                    and target_tag.redundancy_scope != "unknown"
                    and source_tag.redundancy_scope != target_tag.redundancy_scope
                ):
                    blockers.append("redundancy_scope_mismatch")
                score = Decimal("0.8300") if not blockers else Decimal("0.5000")
                candidate = _upsert_candidate(
                    session=session,
                    rule_set=rule_set,
                    mapping_level=MappingLevel.SERVICE_TIER.value,
                    source_provider_id=source.product.provider_id,
                    source_entity_type="service_tier",
                    source_entity_id=source.id,
                    target_provider_id=target.product.provider_id,
                    target_entity_type="service_tier",
                    target_entity_id=target.id,
                    relationship_type=(
                        MappingRelationshipType.CLOSE_ALTERNATIVE.value
                        if not blockers
                        else MappingRelationshipType.PARTIAL_OVERLAP.value
                    ),
                    candidate_status=(
                        MappingCandidateStatus.CANDIDATE.value
                        if not blockers
                        else MappingCandidateStatus.NOT_COMPARABLE.value
                    ),
                    raw_score=score * Decimal("100"),
                    normalized_score=score,
                    confidence=Decimal("0.7200"),
                    blocking_reasons=blockers,
                    conditions=conditions,
                    explanation=(
                        "Object storage tier candidate uses access pattern and redundancy tags; "
                        "similar names alone are not sufficient."
                    ),
                    now=now,
                )
                if source.evidence_id:
                    _link_evidence(
                        session,
                        candidate,
                        source.evidence_id,
                        MappingEvidenceRole.SOURCE_FIELD.value,
                        now,
                    )
                if target.evidence_id:
                    _link_evidence(
                        session,
                        candidate,
                        target.evidence_id,
                        MappingEvidenceRole.TARGET_FIELD.value,
                        now,
                    )
                created += 1
    return created


def _upsert_candidate(
    *,
    session: Session,
    rule_set: MappingRuleSet,
    mapping_level: str,
    source_provider_id: int,
    source_entity_type: str,
    source_entity_id: int,
    target_provider_id: int,
    target_entity_type: str,
    target_entity_id: int,
    relationship_type: str,
    candidate_status: str,
    raw_score: Decimal,
    normalized_score: Decimal,
    confidence: Decimal,
    blocking_reasons: list[str],
    conditions: list[str],
    explanation: str,
    now: datetime,
) -> MappingCandidate:
    candidate = session.scalar(
        select(MappingCandidate).where(
            MappingCandidate.rule_set_id == rule_set.id,
            MappingCandidate.source_entity_type == source_entity_type,
            MappingCandidate.source_entity_id == source_entity_id,
            MappingCandidate.target_entity_type == target_entity_type,
            MappingCandidate.target_entity_id == target_entity_id,
            MappingCandidate.mapping_level == mapping_level,
        )
    )
    values = {
        "source_provider_id": source_provider_id,
        "target_provider_id": target_provider_id,
        "relationship_type": relationship_type,
        "candidate_status": candidate_status,
        "raw_score": raw_score,
        "normalized_score": normalized_score,
        "confidence": confidence,
        "blocking_reasons": blocking_reasons,
        "conditions": conditions,
        "explanation": explanation,
        "generated_at": now,
        "valid_from": now,
        "review_status": ReviewStatus.PENDING_REVIEW.value,
    }
    if candidate is None:
        candidate = MappingCandidate(
            mapping_level=mapping_level,
            source_entity_type=source_entity_type,
            source_entity_id=source_entity_id,
            target_entity_type=target_entity_type,
            target_entity_id=target_entity_id,
            rule_set_id=rule_set.id,
            **values,
        )
        session.add(candidate)
        session.flush()
    else:
        if (
            candidate.candidate_status
            in {
                MappingCandidateStatus.APPROVED.value,
                MappingCandidateStatus.CORRECTED.value,
                MappingCandidateStatus.REJECTED.value,
                MappingCandidateStatus.SUPERSEDED.value,
            }
            or candidate.review_status == ReviewStatus.HUMAN_REVIEWED.value
        ):
            return candidate
        changed = False
        for key, value in values.items():
            if key in {"review_status", "generated_at", "valid_from"}:
                continue
            if getattr(candidate, key) != value:
                setattr(candidate, key, value)
                changed = True
        if changed:
            candidate.generated_at = now
            candidate.valid_from = now
    return candidate


def _link_evidence(
    session: Session, candidate: MappingCandidate, evidence_id: int, role: str, now: datetime
) -> None:
    if (
        candidate.candidate_status
        in {
            MappingCandidateStatus.APPROVED.value,
            MappingCandidateStatus.CORRECTED.value,
            MappingCandidateStatus.REJECTED.value,
            MappingCandidateStatus.SUPERSEDED.value,
        }
        or candidate.review_status == ReviewStatus.HUMAN_REVIEWED.value
    ):
        return
    exists = session.scalar(
        select(MappingCandidateEvidence.id).where(
            MappingCandidateEvidence.mapping_candidate_id == candidate.id,
            MappingCandidateEvidence.evidence_id == evidence_id,
            MappingCandidateEvidence.evidence_role == role,
        )
    )
    if exists is None:
        session.add(
            MappingCandidateEvidence(
                mapping_candidate_id=candidate.id,
                evidence_id=evidence_id,
                evidence_role=role,
                created_at=now,
            )
        )


def _add_sku_field_comparisons(
    session: Session,
    candidate: MappingCandidate,
    source_values: dict[str, NormalizedSpecification],
    target_values: dict[str, NormalizedSpecification],
    now: datetime,
) -> None:
    if (
        candidate.candidate_status
        in {
            MappingCandidateStatus.APPROVED.value,
            MappingCandidateStatus.CORRECTED.value,
            MappingCandidateStatus.REJECTED.value,
            MappingCandidateStatus.SUPERSEDED.value,
        }
        or candidate.review_status == ReviewStatus.HUMAN_REVIEWED.value
    ):
        return
    for field_code in ["compute.cpu.vcpu_count", "compute.memory.capacity_gib"]:
        source = source_values.get(field_code)
        target = target_values.get(field_code)
        if source is None or target is None:
            continue
        status = (
            FieldComparisonStatus.MATCH.value
            if source.numeric_value == target.numeric_value
            else FieldComparisonStatus.CLOSE.value
        )
        exists = session.scalar(
            select(MappingFieldComparison.id).where(
                MappingFieldComparison.mapping_candidate_id == candidate.id,
                MappingFieldComparison.canonical_field_id == source.canonical_field_id,
                MappingFieldComparison.source_value_id == source.id,
                MappingFieldComparison.target_value_id == target.id,
            )
        )
        if exists is None:
            session.add(
                MappingFieldComparison(
                    mapping_candidate_id=candidate.id,
                    canonical_field_id=source.canonical_field_id,
                    source_value_id=source.id,
                    target_value_id=target.id,
                    semantic_status=status,
                    unit_status=(
                        FieldComparisonStatus.MATCH.value
                        if source.canonical_unit == target.canonical_unit
                        else FieldComparisonStatus.DIFFERENT.value
                    ),
                    scope_status=(
                        FieldComparisonStatus.MATCH.value
                        if source.scope_type == target.scope_type
                        else FieldComparisonStatus.DIFFERENT.value
                    ),
                    qualifier_status=(
                        FieldComparisonStatus.MATCH.value
                        if source.value_qualifier == target.value_qualifier
                        else FieldComparisonStatus.DIFFERENT.value
                    ),
                    freshness_status="unknown",
                    evidence_status=FieldComparisonStatus.MATCH.value,
                    comparison_status=status,
                    similarity_score=Decimal("1.0000")
                    if status == FieldComparisonStatus.MATCH.value
                    else Decimal("0.8500"),
                    blocking_reason=None,
                    conditions=["field-level evidence preserved"],
                    created_at=now,
                )
            )
        _link_evidence(
            session, candidate, source.evidence_id, MappingEvidenceRole.SOURCE_FIELD.value, now
        )
        _link_evidence(
            session, candidate, target.evidence_id, MappingEvidenceRole.TARGET_FIELD.value, now
        )


def _product(session: Session, provider_code: str, product_code: str) -> Product | None:
    return session.scalar(
        select(Product)
        .join(Provider, Product.provider_id == Provider.id)
        .where(Provider.code == provider_code, Product.code == product_code)
    )


def _families(session: Session, provider_code: str, product_code: str) -> list[ProductFamily]:
    return list(
        session.scalars(
            select(ProductFamily)
            .join(Product, ProductFamily.product_id == Product.id)
            .join(Provider, Product.provider_id == Provider.id)
            .where(Provider.code == provider_code, Product.code == product_code)
            .order_by(ProductFamily.family_code)
        ).all()
    )


def _skus(session: Session, provider_code: str, product_code: str) -> list[SKU]:
    return list(
        session.scalars(
            select(SKU)
            .join(Product, SKU.product_id == Product.id)
            .join(Provider, Product.provider_id == Provider.id)
            .where(Provider.code == provider_code, Product.code == product_code)
            .order_by(SKU.provider_sku_code)
        ).all()
    )


def _tiers(session: Session, provider_code: str, product_code: str) -> list[ServiceTier]:
    return list(
        session.scalars(
            select(ServiceTier)
            .join(Product, ServiceTier.product_id == Product.id)
            .join(Provider, Product.provider_id == Provider.id)
            .where(Provider.code == provider_code, Product.code == product_code)
            .order_by(ServiceTier.tier_code)
        ).all()
    )


def _first_product_evidence(session: Session, product_id: int) -> int | None:
    product = session.get(Product, product_id)
    if product is None or not product.description:
        return None
    statement: Select[tuple[int | None]] = (
        select(ParsedFieldCandidate.evidence_id)
        .join(SourceDocument, ParsedFieldCandidate.source_document_id == SourceDocument.id)
        .join(SnapshotRecord, ParsedFieldCandidate.snapshot_record_id == SnapshotRecord.id)
        .where(
            ParsedFieldCandidate.target_identity == f"product:{product.code}",
            ParsedFieldCandidate.field_code == "product.description",
            ParsedFieldCandidate.raw_value == product.description,
            ParsedFieldCandidate.evidence_id.is_not(None),
            SourceDocument.provider_id == product.provider_id,
            SourceDocument.authority_level.in_(
                [AuthorityLevel.OFFICIAL_PRIMARY.value, AuthorityLevel.OFFICIAL_SECONDARY.value]
            ),
            SourceDocument.is_current.is_(True),
            SourceDocument.content_hash == SnapshotRecord.content_hash,
            SnapshotRecord.is_current.is_(True),
        )
        .order_by(ParsedFieldCandidate.id.desc())
        .limit(1)
    )
    return session.scalar(statement)


def _sku_values(session: Session, sku_id: int) -> dict[str, NormalizedSpecification]:
    return _sku_values_for_skus(session, [sku_id]).get(sku_id, {})


def _sku_values_for_skus(
    session: Session, sku_ids: list[int]
) -> dict[int, dict[str, NormalizedSpecification]]:
    if not sku_ids:
        return {}
    rows = session.scalars(
        current_normalized_statement()
        .join(
            CanonicalFieldDefinition,
            NormalizedSpecification.canonical_field_id == CanonicalFieldDefinition.id,
        )
        .where(
            NormalizedSpecification.sku_id.in_(sku_ids),
            CanonicalFieldDefinition.code.in_(
                ["compute.cpu.vcpu_count", "compute.memory.capacity_gib"]
            ),
        )
        .order_by(
            NormalizedSpecification.sku_id,
            CanonicalFieldDefinition.code,
            NormalizedSpecification.id.desc(),
        )
    ).all()
    values: dict[int, dict[str, NormalizedSpecification]] = {}
    hash_cache: HashCache = {}
    for row in rows:
        if row.sku_id is None or not normalized_evidence_valid(session, row, hash_cache=hash_cache):
            continue
        values.setdefault(row.sku_id, {}).setdefault(row.canonical_field.code, row)
    return values


def _numeric_value(values: dict[str, NormalizedSpecification], field_code: str) -> Decimal | None:
    value = values.get(field_code)
    return value.numeric_value if value is not None else None


def _normalized_architecture(value: str | None) -> str:
    if value is None:
        return "unknown"
    text = value.lower()
    if "arm" in text or "graviton" in text or "kunpeng" in text:
        return "arm64"
    if "x86" in text or "amd" in text or "intel" in text:
        return "x86_64"
    return "unknown"
