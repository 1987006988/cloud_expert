import argparse
import csv
import io
import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import _bootstrap  # noqa: F401
from sqlalchemy import select
from sqlalchemy.orm import Session

from cloud_expert.database.models.parsing import ParsedFieldCandidate, ParsingRun
from cloud_expert.database.models.product import SKU, Product
from cloud_expert.database.models.product_extension import ProductFamily, ProductSLA, ServiceTier
from cloud_expert.database.models.snapshot import SnapshotRecord
from cloud_expert.database.models.source import Evidence
from cloud_expert.database.models.specification import ProductSpecification, SpecificationDefinition
from cloud_expert.database.session import SessionLocal
from cloud_expert.ingestion.storage.atomic_write import atomic_write_text

CSV_FIELDS = [
    "entity_type",
    "entity_name",
    "field_code",
    "raw_value",
    "normalized_value",
    "source_url",
    "snapshot_path",
    "locator",
    "excerpt",
    "confidence",
    "review_result",
    "reviewer_notes",
]


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate a manual review sample.")
    parser.add_argument("--provider", default="huawei_cloud")
    parser.add_argument("--product", default=None)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("reports/review_samples/week03_manual_review_sample.csv"),
    )
    args = parser.parse_args()

    with SessionLocal() as session:
        if args.provider in {"aws", "aliyun"} or args.product:
            product_codes = [args.product] if args.product else ["ec2", "s3"]
            if args.provider == "aliyun" and args.product is None:
                product_codes = ["ecs", "oss"]
            rows = build_generic_sample(
                session,
                provider_code=args.provider,
                product_codes=product_codes,
            )
        else:
            rows = build_week03_sample(session, provider_code=args.provider)

    content = _to_csv(rows)
    atomic_write_text(args.output, content)
    print(json.dumps({"output": str(args.output), "rows": len(rows)}, ensure_ascii=False, indent=2))
    return 0


def build_week03_sample(session: Session, *, provider_code: str) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    seen: set[tuple[str, str, str, str, str]] = set()

    def add(row: dict[str, str]) -> None:
        key = (
            row["entity_type"],
            row["entity_name"],
            row["field_code"],
            row["raw_value"],
            row["locator"],
        )
        if key not in seen:
            rows.append(row)
            seen.add(key)

    for product_code in ("ecs", "obs"):
        for row in _product_candidate_rows(session, product_code=product_code, limit=5):
            add(row)

    for row in _ecs_family_rows(session, limit=5):
        add(row)
    for row in _ecs_sku_core_rows(session, sku_limit=10):
        add(row)
    for row in _spec_rows(
        session,
        product_code="ecs",
        field_codes=("network.max_bandwidth_gbps", "network.max_pps"),
        limit=5,
    ):
        add(row)
    for row in _region_evidence_rows(session, product_code="ecs", limit=5):
        add(row)
    for row in _sla_rows(session, product_code="ecs"):
        add(row)

    for row in _service_tier_rows(session):
        add(row)
    for row in _spec_rows(
        session,
        product_code="obs",
        field_codes=(
            "object_storage.durability_percentage",
            "object_storage.availability_percentage",
            "object_storage.max_object_size_gib",
        ),
        limit=10,
    ):
        add(row)
    for row in _spec_rows(
        session,
        product_code="obs",
        field_codes=(
            "object_storage.lifecycle_management_supported",
            "object_storage.versioning_supported",
            "object_storage.cross_region_replication_supported",
            "object_storage.server_side_encryption_supported",
            "object_storage.customer_managed_key_supported",
            "object_storage.static_website_hosting_supported",
            "object_storage.event_notification_supported",
        ),
        limit=5,
    ):
        add(row)
    for row in _region_evidence_rows(session, product_code="obs", limit=5):
        add(row)
    for row in _sla_rows(session, product_code="obs"):
        add(row)

    return rows


def build_generic_sample(
    session: Session,
    *,
    provider_code: str,
    product_codes: list[str],
) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    seen: set[tuple[str, str, str, str, str]] = set()

    def add(row: dict[str, str]) -> None:
        key = (
            row["entity_type"],
            row["entity_name"],
            row["field_code"],
            row["raw_value"],
            row["locator"],
        )
        if key not in seen:
            rows.append(row)
            seen.add(key)

    for product_code in product_codes:
        for target_table, limit in (
            ("product", 8),
            ("product_family", 12),
            ("sku", 40),
            ("service_tier", 20),
            ("availability", 20),
            ("zone_availability", 20),
            ("product_sla", 12),
            ("product_specification", 30),
        ):
            for row in _candidate_rows(
                session,
                provider_code=provider_code,
                product_code=product_code,
                target_table=target_table,
                limit=limit,
            ):
                add(row)
    return rows


def _candidate_rows(
    session: Session,
    *,
    provider_code: str,
    product_code: str,
    target_table: str,
    limit: int,
) -> Iterable[dict[str, str]]:
    statement = (
        select(ParsedFieldCandidate, ParsingRun)
        .join(ParsingRun, ParsedFieldCandidate.parsing_run_id == ParsingRun.id)
        .where(
            ParsedFieldCandidate.target_table == target_table,
            ParsingRun.source_id.like(f"{provider_code}_{product_code}_%"),
        )
        .order_by(ParsingRun.source_id, ParsedFieldCandidate.target_identity)
        .limit(limit)
    )
    for candidate, run in session.execute(statement):
        evidence = session.get(Evidence, candidate.evidence_id) if candidate.evidence_id else None
        yield _sample_row(
            session,
            evidence=evidence,
            entity_type=target_table,
            entity_name=candidate.target_identity,
            field_code=candidate.field_code,
            raw_value=candidate.raw_value,
            normalized_value=candidate.normalized_value,
            locator=candidate.locator,
            excerpt=candidate.excerpt,
            confidence=candidate.confidence,
            fallback_source_id=run.source_id,
        )


def _product_candidate_rows(
    session: Session,
    *,
    product_code: str,
    limit: int,
) -> Iterable[dict[str, str]]:
    statement = (
        select(ParsedFieldCandidate, ParsingRun)
        .join(ParsingRun, ParsedFieldCandidate.parsing_run_id == ParsingRun.id)
        .where(
            ParsedFieldCandidate.target_table == "product",
            ParsingRun.source_id.like(f"huawei_cloud_{product_code}_%"),
        )
        .order_by(ParsingRun.source_id, ParsedFieldCandidate.field_code)
        .limit(limit)
    )
    for candidate, run in session.execute(statement):
        evidence = session.get(Evidence, candidate.evidence_id) if candidate.evidence_id else None
        yield _sample_row(
            session,
            evidence=evidence,
            entity_type="product_field",
            entity_name=product_code,
            field_code=candidate.field_code,
            raw_value=candidate.raw_value,
            normalized_value=candidate.normalized_value,
            locator=candidate.locator,
            excerpt=candidate.excerpt,
            confidence=candidate.confidence,
            fallback_source_id=run.source_id,
        )


def _ecs_family_rows(session: Session, *, limit: int) -> Iterable[dict[str, str]]:
    statement = (
        select(ProductFamily)
        .join(Product, ProductFamily.product_id == Product.id)
        .where(Product.code == "ecs")
        .order_by(ProductFamily.family_code)
        .limit(limit)
    )
    for family in session.scalars(statement):
        yield _sample_row(
            session,
            evidence=family.evidence,
            entity_type="product_family",
            entity_name=family.family_code,
            field_code="ecs.instance_family",
            raw_value=family.family_name,
            normalized_value=family.family_code,
            locator=None,
            excerpt=None,
            confidence=None,
        )


def _ecs_sku_core_rows(session: Session, *, sku_limit: int) -> Iterable[dict[str, str]]:
    statement = (
        select(ProductSpecification, SpecificationDefinition, SKU)
        .join(
            SpecificationDefinition,
            ProductSpecification.definition_id == SpecificationDefinition.id,
        )
        .join(Product, ProductSpecification.product_id == Product.id)
        .join(SKU, ProductSpecification.sku_id == SKU.id)
        .where(
            Product.code == "ecs",
            SpecificationDefinition.code.in_(("compute.vcpu_count", "compute.memory_gib")),
        )
        .order_by(SKU.provider_sku_code, SpecificationDefinition.code)
    )
    seen_skus: set[str] = set()
    for spec, definition, sku in session.execute(statement):
        if sku.provider_sku_code not in seen_skus and len(seen_skus) >= sku_limit:
            continue
        seen_skus.add(sku.provider_sku_code)
        yield _spec_sample_row(
            session,
            spec,
            definition,
            entity_type="sku_parameter",
            entity_name=sku.provider_sku_code,
        )


def _spec_rows(
    session: Session,
    *,
    product_code: str,
    field_codes: tuple[str, ...],
    limit: int,
) -> Iterable[dict[str, str]]:
    statement = (
        select(ProductSpecification, SpecificationDefinition, Product, SKU)
        .join(
            SpecificationDefinition,
            ProductSpecification.definition_id == SpecificationDefinition.id,
        )
        .join(Product, ProductSpecification.product_id == Product.id)
        .outerjoin(SKU, ProductSpecification.sku_id == SKU.id)
        .where(Product.code == product_code, SpecificationDefinition.code.in_(field_codes))
        .order_by(SpecificationDefinition.code, ProductSpecification.id)
        .limit(limit)
    )
    for spec, definition, product, sku in session.execute(statement):
        entity_name = sku.provider_sku_code if sku else product.code
        entity_type = "sku_parameter" if sku else "product_parameter"
        yield _spec_sample_row(
            session, spec, definition, entity_type=entity_type, entity_name=entity_name
        )


def _region_evidence_rows(
    session: Session,
    *,
    product_code: str,
    limit: int,
) -> Iterable[dict[str, str]]:
    statement = (
        select(ParsedFieldCandidate, ParsingRun)
        .join(ParsingRun, ParsedFieldCandidate.parsing_run_id == ParsingRun.id)
        .where(
            ParsedFieldCandidate.target_table == "product",
            ParsingRun.source_id == f"huawei_cloud_{product_code}_regions",
        )
        .order_by(ParsedFieldCandidate.field_code)
        .limit(limit)
    )
    for candidate, run in session.execute(statement):
        evidence = session.get(Evidence, candidate.evidence_id) if candidate.evidence_id else None
        yield _sample_row(
            session,
            evidence=evidence,
            entity_type="region_evidence",
            entity_name=product_code,
            field_code=candidate.field_code,
            raw_value=candidate.raw_value,
            normalized_value=candidate.normalized_value,
            locator=candidate.locator,
            excerpt=candidate.excerpt,
            confidence=candidate.confidence,
            fallback_source_id=run.source_id,
        )


def _service_tier_rows(session: Session) -> Iterable[dict[str, str]]:
    statement = (
        select(ServiceTier)
        .join(Product, ServiceTier.product_id == Product.id)
        .where(Product.code == "obs")
        .order_by(ServiceTier.tier_code)
    )
    for tier in session.scalars(statement):
        yield _sample_row(
            session,
            evidence=tier.evidence,
            entity_type="service_tier",
            entity_name=tier.tier_code,
            field_code="obs.storage_class",
            raw_value=tier.official_name,
            normalized_value=tier.tier_code,
            locator=None,
            excerpt=None,
            confidence=None,
        )


def _sla_rows(session: Session, *, product_code: str) -> Iterable[dict[str, str]]:
    statement = (
        select(ProductSLA)
        .join(Product, ProductSLA.product_id == Product.id)
        .where(Product.code == product_code)
        .order_by(ProductSLA.scope, ProductSLA.metric_name, ProductSLA.raw_value)
    )
    for sla in session.scalars(statement):
        yield _sample_row(
            session,
            evidence=sla.evidence,
            entity_type="sla",
            entity_name=f"{product_code}:{sla.scope}",
            field_code=f"sla.{sla.record_type}",
            raw_value=sla.raw_value,
            normalized_value=sla.normalized_percentage,
            locator=None,
            excerpt=None,
            confidence=None,
        )


def _spec_sample_row(
    session: Session,
    spec: ProductSpecification,
    definition: SpecificationDefinition,
    *,
    entity_type: str,
    entity_name: str,
) -> dict[str, str]:
    normalized: Any = spec.canonical_value
    if normalized is None:
        normalized = spec.numeric_value or spec.text_value or spec.boolean_value
    return _sample_row(
        session,
        evidence=spec.evidence,
        entity_type=entity_type,
        entity_name=entity_name,
        field_code=definition.code,
        raw_value=spec.raw_value,
        normalized_value=normalized,
        locator=None,
        excerpt=None,
        confidence=None,
    )


def _sample_row(
    session: Session,
    *,
    evidence: Evidence | None,
    entity_type: str,
    entity_name: str,
    field_code: str,
    raw_value: Any,
    normalized_value: Any,
    locator: str | None,
    excerpt: str | None,
    confidence: float | None,
    fallback_source_id: str | None = None,
) -> dict[str, str]:
    source_url = ""
    snapshot_path = ""
    if evidence:
        source_url = evidence.source_document.url
        snapshot = (
            session.get(SnapshotRecord, evidence.snapshot_record_id)
            if evidence.snapshot_record_id
            else None
        )
        snapshot_path = (
            snapshot.storage_path if snapshot else evidence.source_document.storage_path or ""
        )
        locator = locator or evidence.locator
        excerpt = excerpt or evidence.excerpt
        confidence = confidence if confidence is not None else evidence.confidence
    elif fallback_source_id:
        source_url = fallback_source_id

    return {
        "entity_type": entity_type,
        "entity_name": entity_name,
        "field_code": field_code,
        "raw_value": _value_text(raw_value),
        "normalized_value": _value_text(normalized_value),
        "source_url": source_url,
        "snapshot_path": snapshot_path,
        "locator": locator or "",
        "excerpt": excerpt or "",
        "confidence": _value_text(confidence),
        "review_result": "",
        "reviewer_notes": "",
    }


def _value_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _to_csv(rows: list[dict[str, str]]) -> str:
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=CSV_FIELDS)
    writer.writeheader()
    for row in rows:
        writer.writerow(row)
    return output.getvalue()


if __name__ == "__main__":
    raise SystemExit(main())
