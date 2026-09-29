from __future__ import annotations

import argparse
import json
from hashlib import sha256
from pathlib import Path
from typing import Any

import _bootstrap  # noqa: F401
from sqlalchemy import select

from cloud_expert.database.models.cloud_partition import CloudPartition
from cloud_expert.database.models.provider import Provider
from cloud_expert.database.models.source import SourceDocument
from cloud_expert.database.session import SessionLocal
from cloud_expert.ingestion.registry.loader import load_registry_entries

REPORT_ROOT = Path("reports/market/source_partition_backfill")


def backfill(*, apply: bool = False) -> dict[str, Any]:
    entries = load_registry_entries()
    index: dict[tuple[str, str], list[Any]] = {}
    for entry in entries:
        if entry.provider_code == "huawei_cloud" and entry.market_mode == "domestic":
            index.setdefault((entry.provider_code, entry.url), []).append(entry)
    with SessionLocal() as session:
        provider = session.scalar(select(Provider).where(Provider.code == "huawei_cloud"))
        if provider is None:
            raise ValueError("Huawei Cloud provider is absent")
        docs = session.scalars(
            select(SourceDocument)
            .where(
                SourceDocument.provider_id == provider.id,
                SourceDocument.cloud_partition.is_(None),
            )
            .order_by(SourceDocument.id)
        ).all()
        changes: list[dict[str, Any]] = []
        for doc in docs:
            matches = index.get(("huawei_cloud", doc.url), [])
            if len(matches) != 1 or matches[0].cloud_partition != "huawei_cn":
                raise ValueError(
                    f"source_document {doc.id} lacks one explicit matching registry scope"
                )
            entry = matches[0]
            changes.append(
                {
                    "source_document_id": doc.id,
                    "source_id": entry.source_id,
                    "source_url": doc.url,
                    "source_content_hash": doc.content_hash,
                    "registry_file": str(entry.registry_file),
                    "previous_partition": None,
                    "new_partition": "huawei_cn",
                }
            )
        partition = session.scalar(
            select(CloudPartition).where(
                CloudPartition.provider_id == provider.id,
                CloudPartition.partition_code == "huawei_cn",
            )
        )
        fingerprint = sha256(
            json.dumps(changes, sort_keys=True, ensure_ascii=False).encode("utf-8")
        ).hexdigest()
        result = {
            "input_fingerprint": fingerprint,
            "matched_source_documents": len(changes),
            "existing_partition_record": partition is not None,
            "changes": changes,
            "applied": apply,
        }
        if not apply:
            return result
        if partition is None:
            session.add(
                CloudPartition(
                    provider_id=provider.id,
                    partition_code="huawei_cn",
                    partition_name="Huawei Cloud domestic registry partition",
                    market_mode="domestic",
                    geography_scope="CN",
                    is_active=True,
                )
            )
        for doc in docs:
            doc.cloud_partition = "huawei_cn"
        session.commit()
    report_dir = REPORT_ROOT / f"run_{fingerprint[:12]}"
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / "validation_results.json"
    if not report_path.exists():
        report_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    result["report_path"] = str(report_path)
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    try:
        result = backfill(apply=args.apply)
    except ValueError as exc:
        print(json.dumps({"valid": False, "error": str(exc)}, ensure_ascii=False, indent=2))
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
