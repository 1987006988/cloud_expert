import argparse
import json
from collections.abc import Mapping
from pathlib import Path

import _bootstrap  # noqa: F401
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session

from cloud_expert.database.models.product import SKU, Product, ProductCategory
from cloud_expert.database.models.provider import Provider
from cloud_expert.database.models.source import Evidence, SourceDocument
from cloud_expert.database.models.specification import ProductSpecification, SpecificationDefinition
from cloud_expert.database.session import SessionLocal

DEFAULT_SOURCE_DBS = (
    Path("test_outputs/week3_huawei_acceptance.sqlite"),
    Path("test_outputs/week4_aws_acceptance.sqlite"),
    Path("test_outputs/week5_aliyun_acceptance_v2.sqlite"),
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build a Week 6 combined projection from prior acceptance databases."
    )
    parser.add_argument("--source-db", action="append", type=Path, default=None)
    args = parser.parse_args()
    source_paths = tuple(args.source_db or DEFAULT_SOURCE_DBS)

    imported: list[dict[str, object]] = []
    with SessionLocal() as target_session:
        for source_path in source_paths:
            imported.append(_import_source_database(source_path, target_session))
        target_session.commit()
    print(json.dumps({"sources": imported}, ensure_ascii=False, indent=2, default=str))
    return 0


def _import_source_database(source_path: Path, target_session: Session) -> dict[str, object]:
    if not source_path.exists():
        return {"source": str(source_path), "error": "source database not found"}
    engine = create_engine(f"sqlite:///{source_path}", future=True)
    try:
        with Session(engine, future=True) as source_session:
            provider_map = _copy_providers(source_session, target_session)
            category_map = _copy_categories(source_session, target_session)
            source_document_map = _copy_source_documents(
                source_session,
                target_session,
                provider_map,
            )
            evidence_map = _copy_evidence(source_session, target_session, source_document_map)
            product_map = _copy_products(
                source_session,
                target_session,
                provider_map,
                category_map,
            )
            sku_map = _copy_skus(source_session, target_session, product_map)
            definition_map = _copy_definitions(source_session, target_session, category_map)
            spec_count = _copy_specifications(
                source_session,
                target_session,
                product_map,
                sku_map,
                definition_map,
                evidence_map,
            )
    finally:
        engine.dispose()
    return {
        "source": str(source_path),
        "providers": len(provider_map),
        "categories": len(category_map),
        "source_documents": len(source_document_map),
        "evidence": len(evidence_map),
        "products": len(product_map),
        "skus": len(sku_map),
        "specification_definitions": len(definition_map),
        "product_specifications": spec_count,
    }


def _copy_providers(source_session: Session, target_session: Session) -> dict[int, int]:
    id_map: dict[int, int] = {}
    for provider in source_session.scalars(select(Provider).order_by(Provider.id)):
        target = target_session.scalar(select(Provider).where(Provider.code == provider.code))
        if target is None:
            target = Provider(
                code=provider.code,
                name=provider.name,
                display_name=provider.display_name,
                provider_type=provider.provider_type,
                official_website=provider.official_website,
                is_active=provider.is_active,
            )
            target_session.add(target)
            target_session.flush()
        id_map[provider.id] = target.id
    return id_map


def _copy_categories(source_session: Session, target_session: Session) -> dict[int, int]:
    id_map: dict[int, int] = {}
    categories = list(source_session.scalars(select(ProductCategory).order_by(ProductCategory.id)))
    for category in categories:
        parent_id = None if category.parent_id is None else id_map.get(category.parent_id)
        target = target_session.scalar(
            select(ProductCategory).where(ProductCategory.code == category.code)
        )
        if target is None:
            target = ProductCategory(
                code=category.code,
                name=category.name,
                parent_id=parent_id,
                description=category.description,
            )
            target_session.add(target)
            target_session.flush()
        id_map[category.id] = target.id
    return id_map


def _copy_source_documents(
    source_session: Session,
    target_session: Session,
    provider_map: dict[int, int],
) -> dict[int, int]:
    id_map: dict[int, int] = {}
    columns = _source_document_columns(source_session)
    selected_columns = ", ".join(column for column in _source_document_select_columns() if column in columns)
    rows = source_session.execute(
        text(f"SELECT {selected_columns} FROM source_document ORDER BY id")
    ).mappings()
    for document in rows:
        target = target_session.scalar(
            select(SourceDocument).where(
                SourceDocument.url == document["url"],
                SourceDocument.content_hash == document["content_hash"],
            )
        )
        if target is None:
            target = SourceDocument(
                provider_id=provider_map[int(document["provider_id"])],
                source_type=str(document["source_type"]),
                title=str(document["title"]),
                url=str(document["url"]),
                cloud_partition=_optional_str(document, "cloud_partition"),
                language=_optional_str(document, "language"),
                authority_level=str(document["authority_level"]),
                content_hash=str(document["content_hash"]),
                storage_path=_optional_str(document, "storage_path"),
                mime_type=_optional_str(document, "mime_type"),
                http_status=_optional_int(document, "http_status"),
                is_current=_optional_bool(document, "is_current", default=True),
            )
            target_session.add(target)
            target_session.flush()
        id_map[int(document["id"])] = target.id
    return id_map


def _source_document_select_columns() -> tuple[str, ...]:
    return (
        "id",
        "provider_id",
        "source_type",
        "title",
        "url",
        "cloud_partition",
        "language",
        "authority_level",
        "content_hash",
        "storage_path",
        "mime_type",
        "http_status",
        "is_current",
    )


def _source_document_columns(source_session: Session) -> set[str]:
    return {
        str(row["name"])
        for row in source_session.execute(text("PRAGMA table_info(source_document)")).mappings()
    }


def _optional_str(row: Mapping[str, object], key: str) -> str | None:
    value = row.get(key)
    return None if value is None else str(value)


def _optional_int(row: Mapping[str, object], key: str) -> int | None:
    value = row.get(key)
    return None if value is None else int(value)


def _optional_bool(row: Mapping[str, object], key: str, *, default: bool) -> bool:
    value = row.get(key)
    if value is None:
        return default
    return bool(value)


def _copy_evidence(
    source_session: Session,
    target_session: Session,
    source_document_map: dict[int, int],
) -> dict[int, int]:
    id_map: dict[int, int] = {}
    for evidence in source_session.scalars(select(Evidence).order_by(Evidence.id)):
        target = Evidence(
            source_document_id=source_document_map[evidence.source_document_id],
            section_title=evidence.section_title,
            page_title=evidence.page_title,
            locator=evidence.locator,
            excerpt=evidence.excerpt,
            evidence_type=evidence.evidence_type,
            snapshot_record_id=None,
            content_hash=evidence.content_hash,
            parser_rule=evidence.parser_rule,
            confidence=evidence.confidence,
            review_status=evidence.review_status,
            reviewed_by=evidence.reviewed_by,
            reviewed_at=evidence.reviewed_at,
        )
        target_session.add(target)
        target_session.flush()
        id_map[evidence.id] = target.id
    return id_map


def _copy_products(
    source_session: Session,
    target_session: Session,
    provider_map: dict[int, int],
    category_map: dict[int, int],
) -> dict[int, int]:
    id_map: dict[int, int] = {}
    for product in source_session.scalars(select(Product).order_by(Product.id)):
        target = target_session.scalar(
            select(Product).where(
                Product.provider_id == provider_map[product.provider_id],
                Product.code == product.code,
            )
        )
        if target is None:
            target = Product(
                provider_id=provider_map[product.provider_id],
                category_id=category_map[product.category_id],
                market_mode=product.market_mode,
                code=product.code,
                official_name=product.official_name,
                display_name=product.display_name,
                description=product.description,
                product_status=product.product_status,
                official_url=product.official_url,
                documentation_url=product.documentation_url,
                first_seen_at=product.first_seen_at,
                last_verified_at=product.last_verified_at,
                metadata_json=product.metadata_json,
            )
            target_session.add(target)
            target_session.flush()
        id_map[product.id] = target.id
    return id_map


def _copy_skus(
    source_session: Session,
    target_session: Session,
    product_map: dict[int, int],
) -> dict[int, int]:
    id_map: dict[int, int] = {}
    for sku in source_session.scalars(select(SKU).order_by(SKU.id)):
        target = target_session.scalar(
            select(SKU).where(
                SKU.product_id == product_map[sku.product_id],
                SKU.provider_sku_code == sku.provider_sku_code,
            )
        )
        if target is None:
            target = SKU(
                product_id=product_map[sku.product_id],
                provider_sku_code=sku.provider_sku_code,
                name=sku.name,
                sku_family=sku.sku_family,
                architecture=sku.architecture,
                operating_system=sku.operating_system,
                status=sku.status,
            )
            target_session.add(target)
            target_session.flush()
        id_map[sku.id] = target.id
    return id_map


def _copy_definitions(
    source_session: Session,
    target_session: Session,
    category_map: dict[int, int],
) -> dict[int, int]:
    id_map: dict[int, int] = {}
    for definition in source_session.scalars(select(SpecificationDefinition).order_by(SpecificationDefinition.id)):
        target = target_session.scalar(
            select(SpecificationDefinition).where(SpecificationDefinition.code == definition.code)
        )
        if target is None:
            target = SpecificationDefinition(
                code=definition.code,
                name=definition.name,
                category_id=category_map[definition.category_id],
                data_type=definition.data_type,
                canonical_unit=definition.canonical_unit,
                description=definition.description,
                is_required=definition.is_required,
            )
            target_session.add(target)
            target_session.flush()
        id_map[definition.id] = target.id
    return id_map


def _copy_specifications(
    source_session: Session,
    target_session: Session,
    product_map: dict[int, int],
    sku_map: dict[int, int],
    definition_map: dict[int, int],
    evidence_map: dict[int, int],
) -> int:
    count = 0
    for spec in source_session.scalars(select(ProductSpecification).order_by(ProductSpecification.id)):
        target_session.add(
            ProductSpecification(
                product_id=product_map[spec.product_id],
                sku_id=None if spec.sku_id is None else sku_map[spec.sku_id],
                definition_id=definition_map[spec.definition_id],
                numeric_value=spec.numeric_value,
                text_value=spec.text_value,
                boolean_value=spec.boolean_value,
                raw_value=spec.raw_value,
                raw_unit=spec.raw_unit,
                canonical_value=spec.canonical_value,
                canonical_unit=spec.canonical_unit,
                evidence_id=evidence_map[spec.evidence_id],
                valid_from=spec.valid_from,
                valid_to=spec.valid_to,
                last_verified_at=spec.last_verified_at,
            )
        )
        count += 1
    target_session.flush()
    return count


if __name__ == "__main__":
    raise SystemExit(main())
