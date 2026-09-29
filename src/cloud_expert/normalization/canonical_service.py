from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from cloud_expert.database.enums import (
    CanonicalDomain,
    ComparabilityStatus,
    NormalizationRuleType,
    NormalizationRunStatus,
    ReviewStatus,
    SpecificationScopeType,
)
from cloud_expert.database.models.canonical import (
    CanonicalFieldDefinition,
    ComparabilityAssessment,
    NormalizationRule,
    NormalizationRun,
    NormalizedSpecification,
)
from cloud_expert.database.models.parsing import ParsedFieldCandidate
from cloud_expert.database.models.product import SKU, Product
from cloud_expert.database.models.provider import Provider
from cloud_expert.database.models.specification import ProductSpecification, SpecificationDefinition
from cloud_expert.normalization.canonical_fields import (
    CANONICAL_FIELD_SEEDS,
    LEGACY_FIELD_MAPPINGS,
    LegacyFieldMapping,
    legacy_mapping_by_source_field,
)
from cloud_expert.normalization.evidence_validity import (
    HashCache,
    current_normalized_statement,
    normalized_evidence_valid,
)
from cloud_expert.normalization.unit_standardization import StandardizedValue, standardize_value
from cloud_expert.parsing.hashing import field_value_hash

PROVIDER_PRODUCT_GROUPS: tuple[tuple[str, tuple[tuple[str, str], ...]], ...] = (
    (
        CanonicalDomain.COMPUTE.value,
        (("huawei_cloud", "ecs"), ("aws", "ec2"), ("aliyun", "ecs")),
    ),
    (
        CanonicalDomain.OBJECT_STORAGE.value,
        (("huawei_cloud", "obs"), ("aws", "s3"), ("aliyun", "oss")),
    ),
)


@dataclass
class CanonicalSeedSummary:
    fields_created: int = 0
    fields_updated: int = 0
    rules_created: int = 0
    rules_updated: int = 0


@dataclass
class NormalizationSummary:
    run_key: str
    records_examined: int = 0
    records_created: int = 0
    records_updated: int = 0
    records_skipped: int = 0
    review_items_created: int = 0
    skipped_reasons: dict[str, int] = field(default_factory=dict)

    def skip(self, reason: str) -> None:
        self.records_skipped += 1
        self.skipped_reasons[reason] = self.skipped_reasons.get(reason, 0) + 1


@dataclass
class ComparabilitySummary:
    assessments_created: int = 0
    assessments_updated: int = 0
    status_counts: dict[str, int] = field(default_factory=dict)

    def count_status(self, status: str) -> None:
        self.status_counts[status] = self.status_counts.get(status, 0) + 1


@dataclass(frozen=True)
class FieldReadiness:
    count: int
    scope_types: frozenset[str]
    canonical_units: frozenset[str]
    value_qualifiers: frozenset[str]
    pending_review_count: int


@dataclass(frozen=True)
class ComparabilityDecision:
    status: str
    reason_code: str
    explanation: str
    evidence_coverage_score: Decimal
    unit_compatibility_score: Decimal
    qualifier_compatibility_score: Decimal
    scope_compatibility_score: Decimal
    overall_score: Decimal
    review_status: str


def seed_canonical_registry(session: Session) -> CanonicalSeedSummary:
    summary = CanonicalSeedSummary()
    field_ids: dict[str, int] = {}
    for seed in CANONICAL_FIELD_SEEDS:
        existing = session.scalar(
            select(CanonicalFieldDefinition).where(CanonicalFieldDefinition.code == seed.code)
        )
        values = {
            "name": seed.name,
            "domain": seed.domain,
            "data_type": seed.data_type,
            "canonical_unit": seed.canonical_unit,
            "unit_dimension": seed.unit_dimension,
            "default_qualifier": seed.default_qualifier,
            "default_scope_type": seed.default_scope_type,
            "description": seed.description,
            "is_comparable": seed.is_comparable,
            "is_active": True,
            "metadata_json": {
                "seeded_by": "week06_canonical_registry",
                **seed.prompt_metadata(),
            },
        }
        if existing is None:
            existing = CanonicalFieldDefinition(code=seed.code, **values)
            session.add(existing)
            session.flush()
            summary.fields_created += 1
        else:
            for key, field_value in values.items():
                setattr(existing, key, field_value)
            summary.fields_updated += 1
        field_ids[seed.code] = existing.id

    for mapping in LEGACY_FIELD_MAPPINGS:
        rule = session.scalar(
            select(NormalizationRule).where(
                NormalizationRule.code == mapping.rule_code,
                NormalizationRule.version == "v1",
            )
        )
        rule_values: dict[str, object] = {
            "rule_type": NormalizationRuleType.FIELD_MAPPING.value,
            "source_field_code": mapping.source_field_code,
            "canonical_field_id": field_ids[mapping.canonical_field_code],
            "source_unit": mapping.source_unit,
            "canonical_unit": mapping.canonical_unit,
            "value_qualifier": mapping.value_qualifier,
            "scope_type": mapping.scope_type,
            "description": mapping.conversion_note
            or f"Map legacy field {mapping.source_field_code} to canonical field.",
            "is_active": True,
            "metadata_json": {"canonical_field_code": mapping.canonical_field_code},
        }
        if rule is None:
            rule = NormalizationRule(code=mapping.rule_code, version="v1", **rule_values)
            session.add(rule)
            summary.rules_created += 1
        else:
            for key, rule_value in rule_values.items():
                setattr(rule, key, rule_value)
            summary.rules_updated += 1
    session.flush()
    return summary


def normalize_specifications(
    session: Session,
    *,
    provider_code: str | None = None,
    product_code: str | None = None,
    source_database_label: str | None = None,
    run_key: str | None = None,
) -> NormalizationSummary:
    seed_canonical_registry(session)
    started_at = datetime.now(UTC)
    actual_run_key = run_key or f"week06_canonical_normalization_{started_at:%Y%m%d%H%M%S}"
    summary = NormalizationSummary(run_key=actual_run_key)
    run = _ensure_normalization_run(
        session,
        run_key=actual_run_key,
        source_database_label=source_database_label,
        product_filter=_product_filter_label(provider_code, product_code),
        started_at=started_at,
    )
    mapping_by_field = legacy_mapping_by_source_field()
    statement = (
        select(ProductSpecification, SpecificationDefinition, Product, Provider)
        .join(
            SpecificationDefinition,
            ProductSpecification.definition_id == SpecificationDefinition.id,
        )
        .join(Product, ProductSpecification.product_id == Product.id)
        .join(Provider, Product.provider_id == Provider.id)
        .order_by(ProductSpecification.id)
    )
    if provider_code is not None:
        statement = statement.where(Provider.code == provider_code)
    if product_code is not None:
        statement = statement.where(Product.code == product_code)

    for spec, definition, product, provider in session.execute(statement):
        summary.records_examined += 1
        mapping = mapping_by_field.get(definition.code)
        if mapping is None:
            summary.skip("no_canonical_mapping")
            continue
        canonical_field = session.scalar(
            select(CanonicalFieldDefinition).where(
                CanonicalFieldDefinition.code == mapping.canonical_field_code
            )
        )
        rule = session.scalar(
            select(NormalizationRule).where(
                NormalizationRule.code == mapping.rule_code,
                NormalizationRule.version == "v1",
            )
        )
        if canonical_field is None or rule is None:
            summary.skip("missing_seeded_registry_record")
            continue
        standardized = standardize_value(
            data_type=canonical_field.data_type,
            raw_value=spec.raw_value,
            numeric_value=spec.numeric_value,
            text_value=spec.text_value,
            boolean_value=spec.boolean_value,
            raw_unit=spec.raw_unit,
            source_canonical_unit=spec.canonical_unit,
            target_unit=canonical_field.canonical_unit,
        )
        if not _has_exactly_one_value(standardized):
            summary.skip("standardized_value_not_usable")
            continue
        scope_type, scope_identity = _infer_scope(session, spec, definition.code, mapping)
        quality_score = _quality_score(standardized, scope_type, mapping.scope_type)
        review_status = (
            ReviewStatus.PENDING_REVIEW.value
            if standardized.requires_review or scope_type != mapping.scope_type
            else ReviewStatus.MACHINE_EXTRACTED.value
        )
        source_hash = field_value_hash(
            definition.code,
            spec.raw_value,
            standardized.canonical_value,
            canonical_field.code,
            scope_type,
            scope_identity,
            mapping.value_qualifier,
        )
        existing = session.scalar(
            select(NormalizedSpecification).where(
                NormalizedSpecification.product_specification_id == spec.id,
                NormalizedSpecification.canonical_field_id == canonical_field.id,
                NormalizedSpecification.scope_type == scope_type,
                NormalizedSpecification.scope_identity == scope_identity,
                NormalizedSpecification.value_qualifier == mapping.value_qualifier,
            )
        )
        values: dict[str, object] = {
            "product_id": product.id,
            "sku_id": spec.sku_id,
            "normalization_rule_id": rule.id,
            "normalization_run_id": run.id,
            "evidence_id": spec.evidence_id,
            "numeric_value": standardized.numeric_value,
            "text_value": standardized.text_value,
            "boolean_value": standardized.boolean_value,
            "raw_value": spec.raw_value,
            "raw_unit": spec.raw_unit,
            "canonical_value": standardized.canonical_value,
            "canonical_unit": standardized.canonical_unit,
            "conversion_notes": standardized.conversion_notes,
            "quality_score": quality_score,
            "review_status": review_status,
            "source_value_hash": source_hash,
        }
        if existing is None:
            normalized = NormalizedSpecification(
                product_specification_id=spec.id,
                canonical_field_id=canonical_field.id,
                scope_type=scope_type,
                scope_identity=scope_identity,
                value_qualifier=mapping.value_qualifier,
                **values,
            )
            session.add(normalized)
            summary.records_created += 1
        elif existing.review_status == ReviewStatus.REJECTED.value:
            summary.skip("rejected_by_human_review")
        elif existing.review_status == ReviewStatus.HUMAN_REVIEWED.value:
            summary.skip("preserved_human_reviewed_history")
        else:
            for key, normalized_value in values.items():
                setattr(existing, key, normalized_value)
            summary.records_updated += 1
        if review_status == ReviewStatus.PENDING_REVIEW.value:
            summary.review_items_created += 1
        _ = provider

    run.records_examined = summary.records_examined
    run.records_created = summary.records_created
    run.records_updated = summary.records_updated
    run.records_skipped = summary.records_skipped
    run.review_items_created = summary.review_items_created
    run.completed_at = datetime.now(UTC)
    run.status = (
        NormalizationRunStatus.PARTIAL.value
        if summary.records_skipped or summary.review_items_created
        else NormalizationRunStatus.SUCCEEDED.value
    )
    session.flush()
    return summary


def assess_comparability(session: Session, *, run_key: str | None = None) -> ComparabilitySummary:
    seed_canonical_registry(session)
    run = _latest_or_named_run(session, run_key)
    summary = ComparabilitySummary()
    hash_cache: HashCache = {}
    now = datetime.now(UTC)
    for domain, group in PROVIDER_PRODUCT_GROUPS:
        maybe_products = [_get_product(session, provider, product) for provider, product in group]
        products: list[Product] = [product for product in maybe_products if product is not None]
        for index, source_product in enumerate(products):
            for target_product in products[index + 1 :]:
                _assess_product_pair(
                    session,
                    source_product,
                    target_product,
                    run,
                    summary,
                    domain,
                    hash_cache=hash_cache,
                    now=now,
                )
    session.flush()
    return summary


def _assess_product_pair(
    session: Session,
    source_product: Product,
    target_product: Product,
    run: NormalizationRun | None,
    summary: ComparabilitySummary,
    domain: str,
    *,
    hash_cache: HashCache,
    now: datetime,
) -> None:
    fields = list(
        session.scalars(
            select(CanonicalFieldDefinition)
            .where(
                CanonicalFieldDefinition.is_active.is_(True),
                CanonicalFieldDefinition.domain == domain,
            )
            .order_by(CanonicalFieldDefinition.code)
        ).all()
    )
    for canonical_field in fields:
        qualifiers = _observed_qualifiers(
            session,
            canonical_field.id,
            source_product.id,
            target_product.id,
            hash_cache=hash_cache,
            now=now,
        )
        # Revisit old machine assessments even when their last valid qualifier disappeared.
        qualifiers.update(
            session.scalars(
                select(ComparabilityAssessment.value_qualifier).where(
                    ComparabilityAssessment.canonical_field_id == canonical_field.id,
                    ComparabilityAssessment.source_product_id == source_product.id,
                    ComparabilityAssessment.target_product_id == target_product.id,
                )
            )
        )
        if not qualifiers:
            qualifiers = {canonical_field.default_qualifier}
        for qualifier in sorted(qualifiers):
            scope_type = canonical_field.default_scope_type
            source_readiness = _normalized_readiness(
                session,
                product_id=source_product.id,
                canonical_field_id=canonical_field.id,
                qualifier=qualifier,
                hash_cache=hash_cache,
                now=now,
            )
            target_readiness = _normalized_readiness(
                session,
                product_id=target_product.id,
                canonical_field_id=canonical_field.id,
                qualifier=qualifier,
                hash_cache=hash_cache,
                now=now,
            )
            decision = _comparability_decision(
                source_readiness,
                target_readiness,
                expected_scope_type=scope_type,
                source_market_mode=source_product.market_mode,
                target_market_mode=target_product.market_mode,
            )
            existing = session.scalar(
                select(ComparabilityAssessment).where(
                    ComparabilityAssessment.canonical_field_id == canonical_field.id,
                    ComparabilityAssessment.source_product_id == source_product.id,
                    ComparabilityAssessment.target_product_id == target_product.id,
                    ComparabilityAssessment.scope_type == scope_type,
                    ComparabilityAssessment.value_qualifier == qualifier,
                )
            )
            if existing is not None and existing.review_status in {
                ReviewStatus.HUMAN_REVIEWED.value,
                ReviewStatus.REJECTED.value,
            }:
                # Preserve historical reviews without counting them as a fresh approval.
                summary.count_status(decision.status)
                continue
            summary.count_status(decision.status)
            values = {
                "normalization_run_id": None if run is None else run.id,
                "status": decision.status,
                "reason_code": decision.reason_code,
                "explanation": decision.explanation,
                "market_scope": f"{source_product.market_mode}_vs_{target_product.market_mode}",
                "evidence_coverage_score": decision.evidence_coverage_score,
                "unit_compatibility_score": decision.unit_compatibility_score,
                "qualifier_compatibility_score": decision.qualifier_compatibility_score,
                "scope_compatibility_score": decision.scope_compatibility_score,
                "overall_score": decision.overall_score,
                "review_status": decision.review_status,
            }
            if existing is None:
                assessment = ComparabilityAssessment(
                    canonical_field_id=canonical_field.id,
                    source_product_id=source_product.id,
                    target_product_id=target_product.id,
                    scope_type=scope_type,
                    value_qualifier=qualifier,
                    **values,
                )
                session.add(assessment)
                summary.assessments_created += 1
            else:
                for key, value in values.items():
                    setattr(existing, key, value)
                summary.assessments_updated += 1


def _ensure_normalization_run(
    session: Session,
    *,
    run_key: str,
    source_database_label: str | None,
    product_filter: str | None,
    started_at: datetime,
) -> NormalizationRun:
    existing = session.scalar(select(NormalizationRun).where(NormalizationRun.run_key == run_key))
    if existing is not None:
        return existing
    run = NormalizationRun(
        run_key=run_key,
        status=NormalizationRunStatus.PARTIAL.value,
        source_database_label=source_database_label,
        product_filter=product_filter,
        started_at=started_at,
        records_examined=0,
        records_created=0,
        records_updated=0,
        records_skipped=0,
        review_items_created=0,
    )
    session.add(run)
    session.flush()
    return run


def _product_filter_label(provider_code: str | None, product_code: str | None) -> str | None:
    if provider_code is None and product_code is None:
        return None
    return f"provider={provider_code or '*'};product={product_code or '*'}"


def _infer_scope(
    session: Session,
    spec: ProductSpecification,
    source_field_code: str,
    mapping: LegacyFieldMapping,
) -> tuple[str, str]:
    if spec.sku_id is not None:
        sku = session.get(SKU, spec.sku_id)
        return SpecificationScopeType.SKU.value, sku.provider_sku_code if sku is not None else str(
            spec.sku_id
        )
    candidate = session.scalar(
        select(ParsedFieldCandidate)
        .where(
            ParsedFieldCandidate.evidence_id == spec.evidence_id,
            ParsedFieldCandidate.field_code == source_field_code,
        )
        .order_by(ParsedFieldCandidate.id)
        .limit(1)
    )
    if candidate is not None and candidate.target_identity:
        if candidate.target_table in {"service_tier", "product_family"}:
            return mapping.scope_type, candidate.target_identity
        if mapping.scope_type != SpecificationScopeType.SKU.value:
            return mapping.scope_type, candidate.target_identity
    return SpecificationScopeType.PRODUCT.value, f"product:{spec.product_id}"


def _quality_score(
    standardized: StandardizedValue,
    actual_scope_type: str,
    expected_scope_type: str,
) -> Decimal:
    score = Decimal("1.0000")
    if standardized.requires_review:
        score -= Decimal("0.2500")
    if actual_scope_type != expected_scope_type:
        score -= Decimal("0.2000")
    if standardized.conversion_notes is not None:
        score -= Decimal("0.0500")
    return max(score, Decimal("0.0000"))


def _has_exactly_one_value(value: StandardizedValue) -> bool:
    return (
        sum(
            item is not None
            for item in (value.numeric_value, value.text_value, value.boolean_value)
        )
        == 1
    )


def _get_product(session: Session, provider_code: str, product_code: str) -> Product | None:
    return session.scalar(
        select(Product)
        .join(Provider, Product.provider_id == Provider.id)
        .where(Provider.code == provider_code, Product.code == product_code)
    )


def _latest_or_named_run(session: Session, run_key: str | None) -> NormalizationRun | None:
    if run_key is not None:
        return session.scalar(select(NormalizationRun).where(NormalizationRun.run_key == run_key))
    return session.scalar(select(NormalizationRun).order_by(NormalizationRun.id.desc()).limit(1))


def _observed_qualifiers(
    session: Session,
    canonical_field_id: int,
    source_product_id: int,
    target_product_id: int,
    *,
    hash_cache: HashCache | None = None,
    now: datetime | None = None,
) -> set[str]:
    cache = hash_cache if hash_cache is not None else {}
    at = now or datetime.now(UTC)
    rows = session.scalars(
        current_normalized_statement(now=at).where(
            NormalizedSpecification.canonical_field_id == canonical_field_id,
            NormalizedSpecification.product_id.in_((source_product_id, target_product_id)),
        )
    )
    return {
        row.value_qualifier
        for row in rows
        if normalized_evidence_valid(session, row, hash_cache=cache, now=at)
    }


def _count_normalized(
    session: Session,
    *,
    product_id: int,
    canonical_field_id: int,
    qualifier: str,
    hash_cache: HashCache | None = None,
    now: datetime | None = None,
) -> int:
    return len(
        _current_normalized_rows(
            session,
            product_id=product_id,
            canonical_field_id=canonical_field_id,
            qualifier=qualifier,
            hash_cache=hash_cache,
            now=now,
        )
    )


def _current_normalized_rows(
    session: Session,
    *,
    product_id: int,
    canonical_field_id: int,
    qualifier: str,
    hash_cache: HashCache | None,
    now: datetime | None,
) -> list[NormalizedSpecification]:
    cache = hash_cache if hash_cache is not None else {}
    at = now or datetime.now(UTC)
    rows = session.scalars(
        current_normalized_statement(now=at).where(
            NormalizedSpecification.product_id == product_id,
            NormalizedSpecification.canonical_field_id == canonical_field_id,
            NormalizedSpecification.value_qualifier == qualifier,
        )
    )
    return [
        row for row in rows if normalized_evidence_valid(session, row, hash_cache=cache, now=at)
    ]


def _normalized_readiness(
    session: Session,
    *,
    product_id: int,
    canonical_field_id: int,
    qualifier: str,
    hash_cache: HashCache | None = None,
    now: datetime | None = None,
) -> FieldReadiness:
    rows = _current_normalized_rows(
        session,
        product_id=product_id,
        canonical_field_id=canonical_field_id,
        qualifier=qualifier,
        hash_cache=hash_cache,
        now=now,
    )
    return FieldReadiness(
        count=len(rows),
        scope_types=frozenset(row.scope_type for row in rows),
        canonical_units=frozenset(row.canonical_unit for row in rows if row.canonical_unit),
        value_qualifiers=frozenset(row.value_qualifier for row in rows),
        pending_review_count=sum(
            row.review_status in {ReviewStatus.PENDING_REVIEW.value, ReviewStatus.UNKNOWN.value}
            or row.evidence.review_status
            in {ReviewStatus.PENDING_REVIEW.value, ReviewStatus.UNKNOWN.value}
            for row in rows
        ),
    )


def _comparability_decision(
    source: FieldReadiness,
    target: FieldReadiness,
    *,
    expected_scope_type: str,
    source_market_mode: str,
    target_market_mode: str,
) -> ComparabilityDecision:
    if source.count == 0 and target.count == 0:
        return ComparabilityDecision(
            ComparabilityStatus.NOT_COMPARABLE.value,
            "missing_both_sides",
            "Neither product has evidence-backed normalized values for this canonical field.",
            Decimal("0.0000"),
            Decimal("0.5000"),
            Decimal("0.5000"),
            Decimal("0.5000"),
            Decimal("0.0000"),
            ReviewStatus.PENDING_REVIEW.value,
        )
    if source.count == 0 or target.count == 0:
        return ComparabilityDecision(
            ComparabilityStatus.PARTIAL.value,
            "missing_one_side",
            "Only one side has evidence-backed normalized values for this canonical field.",
            Decimal("0.5000"),
            Decimal("0.5000"),
            Decimal("0.5000"),
            Decimal("0.5000"),
            Decimal("0.5000"),
            ReviewStatus.PENDING_REVIEW.value,
        )
    if source.pending_review_count or target.pending_review_count:
        return ComparabilityDecision(
            ComparabilityStatus.NEEDS_REVIEW.value,
            "pending_review_values",
            "Both sides have current normalized evidence, but at least one value still requires review.",
            Decimal("0.7500"),
            Decimal("1.0000"),
            Decimal("1.0000"),
            Decimal("1.0000"),
            Decimal("0.7500"),
            ReviewStatus.PENDING_REVIEW.value,
        )
    scope_mismatch = (
        source.scope_types != target.scope_types
        or bool(source.scope_types - {expected_scope_type})
        or bool(target.scope_types - {expected_scope_type})
    )
    if scope_mismatch:
        return ComparabilityDecision(
            ComparabilityStatus.NEEDS_REVIEW.value,
            "scope_mismatch",
            "Both sides have values, but normalized scopes do not align with each other or the canonical default scope.",
            Decimal("1.0000"),
            Decimal("1.0000"),
            Decimal("1.0000"),
            Decimal("0.2500"),
            Decimal("0.2500"),
            ReviewStatus.PENDING_REVIEW.value,
        )
    if source.canonical_units != target.canonical_units:
        return ComparabilityDecision(
            ComparabilityStatus.NEEDS_REVIEW.value,
            "unit_mismatch",
            "Both sides have values, but canonical unit sets do not align.",
            Decimal("1.0000"),
            Decimal("0.2500"),
            Decimal("1.0000"),
            Decimal("1.0000"),
            Decimal("0.2500"),
            ReviewStatus.PENDING_REVIEW.value,
        )
    if source.value_qualifiers != target.value_qualifiers:
        return ComparabilityDecision(
            ComparabilityStatus.NEEDS_REVIEW.value,
            "qualifier_mismatch",
            "Both sides have values, but value qualifier sets do not align.",
            Decimal("1.0000"),
            Decimal("1.0000"),
            Decimal("0.2500"),
            Decimal("1.0000"),
            Decimal("0.2500"),
            ReviewStatus.PENDING_REVIEW.value,
        )
    if source_market_mode != target_market_mode:
        return ComparabilityDecision(
            ComparabilityStatus.PARTIAL.value,
            "market_scope_differs",
            "Both sides have normalized values, but their domestic/international market scopes differ.",
            Decimal("0.7500"),
            Decimal("1.0000"),
            Decimal("1.0000"),
            Decimal("1.0000"),
            Decimal("0.7500"),
            ReviewStatus.PENDING_REVIEW.value,
        )
    return ComparabilityDecision(
        ComparabilityStatus.COMPARABLE.value,
        "field_unit_scope_aligned",
        "Both sides have evidence-backed normalized values with aligned field, unit, qualifier, and scope.",
        Decimal("1.0000"),
        Decimal("1.0000"),
        Decimal("1.0000"),
        Decimal("1.0000"),
        Decimal("1.0000"),
        ReviewStatus.MACHINE_EXTRACTED.value,
    )
