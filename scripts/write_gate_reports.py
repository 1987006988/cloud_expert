from __future__ import annotations

import json
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from _bootstrap import ROOT
from check_week07_gate import check_week07_gate
from check_week08_gate import check_week08_gate
from check_week09_gate import check_week09_gate
from sqlalchemy import func, select

from cloud_expert.database.models.evidence_package import EvidencePackage, EvidenceReference
from cloud_expert.database.models.mapping import MappingCandidate, MappingFieldComparison
from cloud_expert.evidence_packages.builder import make_session
from cloud_expert.evidence_packages.validation import (
    customer_output_eligibility_summary,
    validate_evidence_references,
)
from cloud_expert.ingestion.storage.atomic_write import atomic_write_text


def _now() -> str:
    return datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(timespec="seconds")


def _write_json(path_parts: tuple[str, ...], payload: dict[str, Any]) -> None:
    path = ROOT.joinpath(*path_parts)
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(path, json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n")


def _write_text(path_parts: tuple[str, ...], content: str) -> None:
    path = ROOT.joinpath(*path_parts)
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(path, content)


def _week7_payload() -> dict[str, Any]:
    gate = check_week07_gate()
    with make_session() as session:
        mapping_candidates = session.scalar(select(func.count()).select_from(MappingCandidate)) or 0
        field_comparisons = (
            session.scalar(select(func.count()).select_from(MappingFieldComparison)) or 0
        )
    return {
        "generated_at": _now(),
        **gate,
        "mapping_candidates": mapping_candidates,
        "mapping_field_comparisons": field_comparisons,
        "approved_mappings_created": False,
        "customer_eligible_outputs_created": False,
    }


def _week8_payload() -> dict[str, Any]:
    gate = check_week08_gate()
    with make_session() as session:
        packages = session.scalar(select(func.count()).select_from(EvidencePackage)) or 0
        references = session.scalar(select(func.count()).select_from(EvidenceReference)) or 0
        reference_validation = validate_evidence_references(session)
        eligibility = customer_output_eligibility_summary(session)
    return {
        "generated_at": _now(),
        **gate,
        "evidence_packages_created": packages,
        "evidence_references_created": references,
        "evidence_reference_validation": reference_validation,
        "customer_output_eligibility": eligibility,
        "pricing_or_tco_created": False,
    }


def _render_week7(payload: dict[str, Any]) -> str:
    return f"""# Week 7 Gate Summary

Generated at: {payload["generated_at"]}

Gate verdict: **WEEK7_GATE={payload["verdict"]}**

R008 was waived by the project owner for internal engineering execution only.
The waiver does not approve pending facts for customer use.

## Current State

| Metric | Value |
| --- | ---: |
| Mapping candidates | {payload["mapping_candidates"]} |
| Field comparisons | {payload["mapping_field_comparisons"]} |
| Approved mappings created | {payload["approved_mappings_created"]} |
| Customer eligible outputs created | {payload["customer_eligible_outputs_created"]} |

## Decision

Week 7 mapping candidate generation may be used internally. Human review remains
required before any customer-eligible comparison output.
"""


def _render_week8(payload: dict[str, Any]) -> str:
    return f"""# Week 8 Gate Summary

Generated at: {payload["generated_at"]}

Gate verdict: **WEEK8_GATE={payload["verdict"]}**

## Current State

| Metric | Value |
| --- | ---: |
| Mapping candidates | {payload["mapping_candidates"]} |
| Mapping evidence links | {payload["mapping_evidence_links"]} |
| Evidence packages | {payload["evidence_packages_created"]} |
| Evidence references | {payload["evidence_references_created"]} |
| Customer eligible packages | {payload["customer_output_eligibility"]["customer_eligible"]} |

## Decision

Evidence packages and internal comparison reports are available for review.
They contain no pricing, no TCO, no superiority claims, and no customer-facing
approval.
"""


def _render_week9(payload: dict[str, Any]) -> str:
    missing = ", ".join(payload["pricing_sources"]["missing_required"]) or "none"
    return f"""# Week 9 Gate Summary

Generated at: {payload["generated_at"]}

Gate verdict: **WEEK9_GATE={payload["verdict"]}**

## Current State

| Area | Value |
| --- | --- |
| Week 7 Gate | {payload["week7_gate"]["verdict"]} |
| Week 8 Gate | {payload["week8_gate"]["verdict"]} |
| Evidence packages | {payload["evidence_packages"]} |
| Evidence references | {payload["evidence_references"]} |
| Pricing registry sources | {payload["pricing_sources"]["registered_pricing_sources"]} |
| Missing required pricing sources | {missing} |
| Pricing SourceDocuments | {payload["pricing_sources"]["pricing_source_documents"]} |
| Pricing Evidence | {payload["pricing_sources"]["pricing_evidence"]} |

## Decision

Week 9 remains blocked because official pricing source readiness is incomplete.
No Pricing/TCO business code should run until official pricing sources are
registered, approved for the intended collection mode, captured as immutable
snapshots, and linked to Evidence.
"""


def _render_blockers(payload: dict[str, Any]) -> str:
    blockers = payload.get("blocking_items") or []
    if not blockers:
        return "# Unresolved Blockers\n\nNo unresolved blockers for this gate.\n"
    lines = ["# Unresolved Blockers", ""]
    lines.extend(f"- {blocker}" for blocker in blockers)
    lines.append("")
    return "\n".join(lines)


def _render_next_actions(payload: dict[str, Any]) -> str:
    if payload["gate"] == "WEEK9_GATE":
        return """# Recommended Next Actions

1. Register missing Huawei Cloud ECS and OBS official pricing sources.
2. Complete terms and collection-mode review for all pricing sources.
3. Capture immutable raw pricing snapshots before parsing any price values.
4. Parse PriceSKU and PriceSnapshot only from official pricing Evidence.
5. Keep missing prices out of totals; do not treat them as zero.
"""
    return """# Recommended Next Actions

1. Keep internal review output clearly marked as not customer eligible.
2. Apply human review decisions before promoting any facts to customer use.
3. Continue to Week 9 only after the pricing source gate is satisfied.
"""


def main() -> int:
    week7 = _week7_payload()
    week8 = _week8_payload()
    week9 = {"generated_at": _now(), **check_week09_gate()}

    for week, payload, renderer in [
        ("week07_gate", week7, _render_week7),
        ("week08_gate", week8, _render_week8),
        ("week09_gate", week9, _render_week9),
    ]:
        _write_json((f"reports/{week}", "validation_results.json"), payload)
        _write_text((f"reports/{week}", "gate_summary.md"), renderer(payload))
        _write_text((f"reports/{week}", "unresolved_blockers.md"), _render_blockers(payload))
        _write_text(
            (f"reports/{week}", "recommended_next_actions.md"), _render_next_actions(payload)
        )

    print(
        json.dumps(
            {
                "week7": week7["verdict"],
                "week8": week8["verdict"],
                "week9": week9["verdict"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
