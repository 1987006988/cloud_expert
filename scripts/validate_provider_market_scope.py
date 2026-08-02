import argparse
import json
from urllib.parse import urlparse

import _bootstrap  # noqa: F401
from sqlalchemy import select
from sqlalchemy.orm import Session

from cloud_expert.database.models.cloud_partition import CloudPartition
from cloud_expert.database.models.product import Product
from cloud_expert.database.models.provider import Provider
from cloud_expert.database.models.region import AvailabilityZone, Region
from cloud_expert.database.models.source import SourceDocument
from cloud_expert.database.session import SessionLocal
from cloud_expert.ingestion.providers.aliyun.common import (
    ALIYUN_PROVIDER_CODE,
    ALIYUN_PUBLIC_CN_PARTITION,
    is_mainland_region_code,
)
from cloud_expert.ingestion.registry.loader import load_registry_entries
from cloud_expert.ingestion.registry.schemas import SourceRegistryEntry


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate provider market scope boundaries.")
    parser.add_argument("--provider", default=None)
    args = parser.parse_args()

    entries = load_registry_entries()
    provider_codes = (
        [args.provider] if args.provider else sorted({entry.provider_code for entry in entries})
    )
    errors: list[str] = []
    checked_registry = 0
    checked_documents = 0
    checked_regions = 0
    checked_zones = 0

    for provider_code in provider_codes:
        provider_entries = [entry for entry in entries if entry.provider_code == provider_code]
        checked_registry += len(provider_entries)
        if provider_code == ALIYUN_PROVIDER_CODE:
            errors.extend(_validate_aliyun_registry(provider_entries))

    with SessionLocal() as session:
        for provider_code in provider_codes:
            if provider_code != ALIYUN_PROVIDER_CODE:
                continue
            document_errors, document_count = _validate_aliyun_documents(session)
            region_errors, region_count = _validate_aliyun_regions(session)
            zone_errors, zone_count = _validate_aliyun_zones(session)
            product_errors = _validate_aliyun_products(session)
            errors.extend(document_errors)
            errors.extend(region_errors)
            errors.extend(zone_errors)
            errors.extend(product_errors)
            checked_documents += document_count
            checked_regions += region_count
            checked_zones += zone_count

    result = {
        "provider": args.provider,
        "registry_sources_checked": checked_registry,
        "source_documents_checked": checked_documents,
        "regions_checked": checked_regions,
        "zones_checked": checked_zones,
        "errors": len(errors),
        "error_messages": errors,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 1 if errors else 0


def _validate_aliyun_registry(entries: list[SourceRegistryEntry]) -> list[str]:
    errors: list[str] = []
    for entry in entries:
        source_id = entry.source_id
        if entry.market_mode != "domestic":
            errors.append(f"{source_id}: market_mode must be domestic.")
        if entry.cloud_partition != ALIYUN_PUBLIC_CN_PARTITION:
            errors.append(f"{source_id}: cloud_partition must be {ALIYUN_PUBLIC_CN_PARTITION}.")
        host = (urlparse(entry.url).hostname or "").lower()
        if "alibabacloud.com" in host:
            errors.append(f"{source_id}: international Alibaba Cloud host is out of scope.")
        if not _is_allowed_aliyun_host(host):
            errors.append(f"{source_id}: host {host} is not an approved Aliyun official host.")
        if entry.source_type == "pricing" and not _is_allowed_aliyun_pricing_mode(entry, host):
            errors.append(
                f"{source_id}: pricing source must be approved help-page automation "
                "or disabled manual-only record."
            )
    return errors


def _validate_aliyun_documents(session: Session) -> tuple[list[str], int]:
    rows = session.execute(
        select(SourceDocument, Provider)
        .join(Provider, SourceDocument.provider_id == Provider.id)
        .where(Provider.code == ALIYUN_PROVIDER_CODE)
    ).all()
    errors: list[str] = []
    for document, _provider in rows:
        if document.cloud_partition != ALIYUN_PUBLIC_CN_PARTITION:
            errors.append(f"source_document:{document.id}: invalid cloud_partition.")
        host = (urlparse(document.url).hostname or "").lower()
        if "alibabacloud.com" in host or not _is_allowed_aliyun_host(host):
            errors.append(f"source_document:{document.id}: out-of-scope host {host}.")
    return errors, len(rows)


def _validate_aliyun_products(session: Session) -> list[str]:
    rows = session.scalars(
        select(Product)
        .join(Provider, Product.provider_id == Provider.id)
        .where(Provider.code == ALIYUN_PROVIDER_CODE)
    ).all()
    errors: list[str] = []
    for product in rows:
        if product.market_mode != "domestic":
            errors.append(f"product:{product.code}: market_mode must be domestic.")
    return errors


def _validate_aliyun_regions(session: Session) -> tuple[list[str], int]:
    rows = session.scalars(
        select(Region)
        .join(Provider, Region.provider_id == Provider.id)
        .join(CloudPartition, Region.cloud_partition_id == CloudPartition.id)
        .where(
            Provider.code == ALIYUN_PROVIDER_CODE,
            CloudPartition.partition_code == ALIYUN_PUBLIC_CN_PARTITION,
        )
    ).all()
    errors: list[str] = []
    for region in rows:
        if not is_mainland_region_code(region.code):
            errors.append(f"region:{region.code}: not in mainland China public scope.")
        if region.market_mode != "domestic":
            errors.append(f"region:{region.code}: market_mode must be domestic.")
    return errors, len(rows)


def _validate_aliyun_zones(session: Session) -> tuple[list[str], int]:
    rows = session.execute(
        select(AvailabilityZone, Region)
        .join(Region, AvailabilityZone.region_id == Region.id)
        .join(Provider, AvailabilityZone.provider_id == Provider.id)
        .join(CloudPartition, AvailabilityZone.cloud_partition_id == CloudPartition.id)
        .where(
            Provider.code == ALIYUN_PROVIDER_CODE,
            CloudPartition.partition_code == ALIYUN_PUBLIC_CN_PARTITION,
        )
    ).all()
    errors: list[str] = []
    for zone, region in rows:
        inferred_region = _region_code_for_zone(zone.zone_code)
        if inferred_region != region.code:
            errors.append(f"zone:{zone.zone_code}: inferred region does not match {region.code}.")
        if not is_mainland_region_code(region.code):
            errors.append(f"zone:{zone.zone_code}: region {region.code} is out of scope.")
        if zone.market_mode != "domestic":
            errors.append(f"zone:{zone.zone_code}: market_mode must be domestic.")
    return errors, len(rows)


def _is_allowed_aliyun_host(host: str) -> bool:
    return host in {"www.aliyun.com", "cn.aliyun.com", "help.aliyun.com", "terms.aliyun.com"}


def _is_allowed_aliyun_pricing_mode(entry: SourceRegistryEntry, host: str) -> bool:
    if (
        host == "help.aliyun.com"
        and entry.enabled
        and entry.allow_automated_fetch
        and not entry.manual_only
        and entry.terms_review_status == "approved"
    ):
        return True
    return not entry.enabled and not entry.allow_automated_fetch and entry.manual_only


def _region_code_for_zone(zone_code: str) -> str:
    return zone_code.rsplit("-", 1)[0] if "-" in zone_code else zone_code


if __name__ == "__main__":
    raise SystemExit(main())
