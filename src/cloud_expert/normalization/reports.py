from collections import defaultdict
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from cloud_expert.database.models.canonical import (
    CanonicalFieldDefinition,
    ComparabilityAssessment,
    NormalizationRule,
    NormalizationRun,
    NormalizedSpecification,
)
from cloud_expert.database.models.product import Product
from cloud_expert.database.models.provider import Provider
from cloud_expert.ingestion.providers.aliyun.ecs.mappings import ALIYUN_ECS_SPEC_DEFINITIONS
from cloud_expert.ingestion.providers.aliyun.oss.mappings import ALIYUN_OSS_SPEC_DEFINITIONS
from cloud_expert.ingestion.providers.aws.ec2.mappings import EC2_SPEC_DEFINITIONS
from cloud_expert.ingestion.providers.aws.s3.mappings import S3_SPEC_DEFINITIONS
from cloud_expert.ingestion.providers.huawei_cloud.ecs.mappings import ECS_SPEC_DEFINITIONS
from cloud_expert.ingestion.providers.huawei_cloud.obs.mappings import OBS_SPEC_DEFINITIONS
from cloud_expert.ingestion.storage.atomic_write import atomic_write_text
from cloud_expert.normalization.canonical_fields import (
    LEGACY_FIELD_MAPPINGS,
    canonical_seed_by_code,
)

PROVIDER_FIELD_SETS: dict[str, dict[str, tuple[str, str, str | None]]] = {
    "huawei_cloud/ecs": ECS_SPEC_DEFINITIONS,
    "huawei_cloud/obs": OBS_SPEC_DEFINITIONS,
    "aws/ec2": EC2_SPEC_DEFINITIONS,
    "aws/s3": S3_SPEC_DEFINITIONS,
    "aliyun/ecs": ALIYUN_ECS_SPEC_DEFINITIONS,
    "aliyun/oss": ALIYUN_OSS_SPEC_DEFINITIONS,
}

FIELD_MATRIX_HEADERS = [
    "canonical_field_code",
    "canonical_name",
    "domain",
    "semantic_group",
    "data_type",
    "canonical_unit",
    "unit_dimension",
    "unit_status",
    "legacy_field_code",
    "value_qualifier",
    "default_qualifier",
    "qualifier_status",
    "scope_type",
    "default_scope_type",
    "scope_status",
    "provider_products",
    "provider_coverage_count",
    "evidence_requirement",
    "evidence_status",
    "comparability_tier",
    "comparability_status",
    "lifecycle_status",
    "deprecated",
    "replacement_field_code",
    "review_policy",
    "notes",
]


def build_field_matrix_rows(domain: str | None = None) -> list[dict[str, str]]:
    seeds = canonical_seed_by_code()
    rows: list[dict[str, str]] = []
    for mapping in sorted(LEGACY_FIELD_MAPPINGS, key=lambda item: item.canonical_field_code):
        seed = seeds[mapping.canonical_field_code]
        if domain is not None and seed.domain != domain:
            continue
        metadata = seed.prompt_metadata()
        provider_products = _providers_for_legacy(mapping.source_field_code)
        rows.append(
            {
                "canonical_field_code": seed.code,
                "canonical_name": seed.name,
                "domain": seed.domain,
                "semantic_group": str(metadata["semantic_group"]),
                "data_type": seed.data_type,
                "canonical_unit": seed.canonical_unit or "",
                "unit_dimension": seed.unit_dimension or "",
                "unit_status": _unit_status(
                    seed.data_type, seed.canonical_unit, seed.unit_dimension
                ),
                "legacy_field_code": mapping.source_field_code,
                "value_qualifier": mapping.value_qualifier,
                "default_qualifier": seed.default_qualifier,
                "qualifier_status": _qualifier_status(
                    mapping.value_qualifier, seed.default_qualifier
                ),
                "scope_type": mapping.scope_type,
                "default_scope_type": seed.default_scope_type,
                "scope_status": _scope_status(mapping.scope_type, seed.default_scope_type),
                "provider_products": ", ".join(provider_products),
                "provider_coverage_count": str(len(provider_products)),
                "evidence_requirement": str(metadata["evidence_requirement"]),
                "evidence_status": _evidence_status(provider_products),
                "comparability_tier": str(metadata["comparability_tier"]),
                "comparability_status": _field_comparability_status(
                    seed.is_comparable, provider_products
                ),
                "lifecycle_status": str(metadata["lifecycle_status"]),
                "deprecated": str(metadata["deprecated"]).lower(),
                "replacement_field_code": str(metadata["replacement_field_code"] or ""),
                "review_policy": str(metadata["review_policy"]),
                "notes": mapping.conversion_note or "",
            }
        )
    return rows


def build_cross_provider_coverage_report(session: Session) -> dict[str, Any]:
    product_rows = list(
        session.execute(
            select(Product, Provider)
            .join(Provider, Product.provider_id == Provider.id)
            .where(Product.code.in_(("ecs", "obs", "ec2", "s3", "oss")))
            .order_by(Provider.code, Product.code)
        ).all()
    )
    field_rows = list(
        session.scalars(
            select(CanonicalFieldDefinition)
            .where(CanonicalFieldDefinition.is_active.is_(True))
            .order_by(CanonicalFieldDefinition.code)
        ).all()
    )
    coverage_rows: list[dict[str, Any]] = []
    for field in field_rows:
        row: dict[str, Any] = {
            "canonical_field_code": field.code,
            "domain": field.domain,
            "data_type": field.data_type,
            "canonical_unit": field.canonical_unit,
            "products": {},
        }
        for product, provider in product_rows:
            key = f"{provider.code}/{product.code}"
            row["products"][key] = _count_normalized(session, product.id, field.id)
        coverage_rows.append(row)
    return {
        "canonical_fields": len(field_rows),
        "products": [f"{provider.code}/{product.code}" for product, provider in product_rows],
        "rows": coverage_rows,
    }


def build_normalization_quality_report(session: Session) -> dict[str, Any]:
    status_counts = _group_count(session, NormalizedSpecification.review_status)
    comparability_counts = _group_count(session, ComparabilityAssessment.status)
    product_counts = _normalized_counts_by_product(session)
    average_quality = session.scalar(select(func.avg(NormalizedSpecification.quality_score)))
    return {
        "canonical_field_definitions": _count_table(session, CanonicalFieldDefinition),
        "normalization_rules": _count_table(session, NormalizationRule),
        "normalization_runs": _count_table(session, NormalizationRun),
        "normalized_specifications": _count_table(session, NormalizedSpecification),
        "comparability_assessments": _count_table(session, ComparabilityAssessment),
        "normalized_review_status_counts": status_counts,
        "comparability_status_counts": comparability_counts,
        "average_quality_score": None
        if average_quality is None
        else str(Decimal(str(average_quality)).quantize(Decimal("0.0001"))),
        "product_normalized_specification_counts": product_counts,
    }


def write_markdown_table(rows: list[dict[str, str]], output_path: Path, *, title: str) -> None:
    headers = FIELD_MATRIX_HEADERS
    lines = [f"# {title}", "", "| " + " | ".join(headers) + " |"]
    lines.append("| " + " | ".join("---" for _ in headers) + " |")
    for row in rows:
        lines.append(
            "| " + " | ".join(_markdown_cell(row.get(header, "")) for header in headers) + " |"
        )
    atomic_write_text(output_path, "\n".join(lines) + "\n")


def write_coverage_markdown(report: dict[str, Any], output_path: Path) -> None:
    products = list(report["products"])
    headers = ["canonical_field_code", "domain", *products]
    lines = ["# Cross-Provider Canonical Coverage", "", "| " + " | ".join(headers) + " |"]
    lines.append("| " + " | ".join("---" for _ in headers) + " |")
    for row in report["rows"]:
        product_counts = row["products"]
        cells = [
            str(row["canonical_field_code"]),
            str(row["domain"]),
            *[str(product_counts.get(product, 0)) for product in products],
        ]
        lines.append("| " + " | ".join(_markdown_cell(cell) for cell in cells) + " |")
    atomic_write_text(output_path, "\n".join(lines) + "\n")


def _providers_for_legacy(source_field_code: str) -> list[str]:
    providers: list[str] = []
    for provider_product, fields in PROVIDER_FIELD_SETS.items():
        if source_field_code in fields:
            providers.append(provider_product)
    return providers


def _unit_status(data_type: str, canonical_unit: str | None, unit_dimension: str | None) -> str:
    if data_type in {"text", "enum", "boolean"} and canonical_unit is None:
        return "unit_not_applicable"
    if canonical_unit and unit_dimension:
        return "canonical_unit_defined"
    return "unit_review_required"


def _qualifier_status(value_qualifier: str, default_qualifier: str) -> str:
    if value_qualifier == default_qualifier:
        return "default_qualifier"
    return "explicit_mapping_qualifier"


def _scope_status(scope_type: str, default_scope_type: str) -> str:
    if scope_type == default_scope_type:
        return "default_scope"
    return "explicit_mapping_scope"


def _evidence_status(provider_products: list[str]) -> str:
    if provider_products:
        return "parser_field_registered"
    return "missing_parser_field"


def _field_comparability_status(is_comparable: bool, provider_products: list[str]) -> str:
    if not is_comparable:
        return "reference_only"
    if len(provider_products) >= 2:
        return "ready_for_blocker_assessment"
    return "limited_provider_coverage"


def _count_normalized(session: Session, product_id: int, canonical_field_id: int) -> int:
    return int(
        session.scalar(
            select(func.count())
            .select_from(NormalizedSpecification)
            .where(
                NormalizedSpecification.product_id == product_id,
                NormalizedSpecification.canonical_field_id == canonical_field_id,
            )
        )
        or 0
    )


def _count_table(session: Session, model: type[Any]) -> int:
    return int(session.scalar(select(func.count()).select_from(model)) or 0)


def _group_count(session: Session, column: Any) -> dict[str, int]:
    return {
        str(key): int(count)
        for key, count in session.execute(select(column, func.count()).group_by(column)).all()
    }


def _normalized_counts_by_product(session: Session) -> dict[str, int]:
    counts: dict[str, int] = defaultdict(int)
    for provider_code, product_code, count in session.execute(
        select(Provider.code, Product.code, func.count())
        .join(Product, NormalizedSpecification.product_id == Product.id)
        .join(Provider, Product.provider_id == Provider.id)
        .select_from(NormalizedSpecification)
        .group_by(Provider.code, Product.code)
    ):
        counts[f"{provider_code}/{product_code}"] = int(count)
    return dict(counts)


def _markdown_cell(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")
