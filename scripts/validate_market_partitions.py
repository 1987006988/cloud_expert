from __future__ import annotations

import json

import _bootstrap  # noqa: F401
from sqlalchemy import func, select

from cloud_expert.database.models.cloud_partition import CloudPartition
from cloud_expert.database.models.source import SourceDocument
from cloud_expert.database.session import SessionLocal
from cloud_expert.ingestion.registry.loader import load_registry_entries


def validate_market_partitions() -> dict[str, object]:
    official_entries = [
        entry
        for entry in load_registry_entries()
        if entry.provider_code in {"huawei_cloud", "aws", "aliyun"}
    ]
    with SessionLocal() as session:
        partitions = session.scalars(select(CloudPartition)).all()
        registered = {
            (partition.provider.code, partition.partition_code, partition.market_mode)
            for partition in partitions
        }
        source_partition_missing = (
            session.scalar(
                select(func.count())
                .select_from(SourceDocument)
                .where(SourceDocument.cloud_partition.is_(None))
            )
            or 0
        )
    registry_errors = [
        entry.source_id
        for entry in official_entries
        if entry.cloud_partition is None
        or (entry.provider_code, entry.cloud_partition, entry.market_mode) not in registered
    ]
    return {
        "official_registry_entries": len(official_entries),
        "partition_records": len(partitions),
        "registry_partition_errors": registry_errors,
        "source_document_partition_missing": source_partition_missing,
        "valid": not registry_errors and source_partition_missing == 0,
    }


def main() -> int:
    result = validate_market_partitions()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
