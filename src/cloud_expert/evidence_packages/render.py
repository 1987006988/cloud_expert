from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from cloud_expert.database.models.evidence_package import EvidencePackage


def package_payload(package: EvidencePackage) -> dict[str, Any]:
    return {
        "package_code": package.package_code,
        "package_version": package.package_version,
        "package_type": package.package_type,
        "rule_set_version": package.rule_set_version,
        "review_status": package.review_status,
        "customer_eligible": package.customer_eligible,
        "limitations": [
            "No pricing or TCO is included.",
            "No performance benchmark or superiority claim is made.",
            "Pending-review information must not be promised to customers.",
            "Facts may vary by Region, scope, qualifier, and capture time.",
        ],
        "items": [
            {
                "display_order": item.display_order,
                "canonical_field": item.canonical_field.code if item.canonical_field else None,
                "source_raw_value": item.source_value.raw_value if item.source_value else None,
                "source_canonical_value": item.source_value.canonical_value
                if item.source_value
                else None,
                "target_raw_value": item.target_value.raw_value if item.target_value else None,
                "target_canonical_value": item.target_value.canonical_value
                if item.target_value
                else None,
                "unit": item.source_value.canonical_unit if item.source_value else None,
                "source_reference": item.source_reference_code,
                "target_reference": item.target_reference_code,
                "comparison_status": item.comparison_status,
                "scope_status": item.scope_status,
                "qualifier_status": item.qualifier_status,
                "freshness_status": item.freshness_status,
                "blocking_reason": item.blocking_reason,
            }
            for item in sorted(package.items, key=lambda row: row.display_order)
        ],
    }


def export_package(session: Session, package_code: str, output_path: Path, fmt: str) -> bool:
    package = session.scalar(
        select(EvidencePackage).where(EvidencePackage.package_code == package_code)
    )
    if package is None:
        return False
    payload = package_payload(package)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if fmt == "json":
        output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    else:
        lines = [
            f"# Evidence Package {payload['package_code']}",
            "",
            f"- Version: `{payload['package_version']}`",
            f"- Type: `{payload['package_type']}`",
            f"- Rule set: `{payload['rule_set_version']}`",
            f"- Review status: `{payload['review_status']}`",
            f"- Customer eligible: `{payload['customer_eligible']}`",
            "",
            "## Compared Fields",
            "",
            "| Field | Source | Target | Status | References |",
            "| --- | --- | --- | --- | --- |",
        ]
        for item in payload["items"]:
            lines.append(
                "| {field} | {source} | {target} | {status} | {refs} |".format(
                    field=item["canonical_field"] or "mapping_context",
                    source=item["source_canonical_value"] or item["source_raw_value"] or "",
                    target=item["target_canonical_value"] or item["target_raw_value"] or "",
                    status=item["comparison_status"],
                    refs=", ".join(
                        ref for ref in [item["source_reference"], item["target_reference"]] if ref
                    ),
                )
            )
        lines.extend(
            [
                "",
                "## Limitations",
                "",
                *[f"- {limitation}" for limitation in payload["limitations"]],
                "",
            ]
        )
        output_path.write_text("\n".join(lines), encoding="utf-8")
    return True
