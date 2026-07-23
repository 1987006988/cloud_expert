from __future__ import annotations

import json

from _bootstrap import ROOT as _ROOT  # noqa: F401
from check_week07_gate import check_week07_gate
from sqlalchemy import func, select

from cloud_expert.database.models.mapping import (
    MappingCandidate,
    MappingCandidateEvidence,
    MappingFieldComparison,
    MappingRuleSet,
)
from cloud_expert.mapping.pipeline import make_session
from cloud_expert.mapping.validation import validate_mapping_evidence


def check_week08_gate() -> dict[str, object]:
    week7 = check_week07_gate()
    with make_session() as session:
        result = {
            "gate": "WEEK8_GATE",
            "week7_gate": week7["verdict"],
            "mapping_rule_sets": session.scalar(select(func.count()).select_from(MappingRuleSet))
            or 0,
            "mapping_candidates": session.scalar(select(func.count()).select_from(MappingCandidate))
            or 0,
            "mapping_field_comparisons": session.scalar(
                select(func.count()).select_from(MappingFieldComparison)
            )
            or 0,
            "mapping_evidence_links": session.scalar(
                select(func.count()).select_from(MappingCandidateEvidence)
            )
            or 0,
            "mapping_evidence": validate_mapping_evidence(session),
        }
    result["verdict"] = (
        "GO"
        if result["week7_gate"] == "GO"
        and result["mapping_rule_sets"] > 0
        and result["mapping_candidates"] > 0
        and result["mapping_field_comparisons"] > 0
        and result["mapping_evidence"]["valid"]
        else "NO-GO"
    )
    return result


def main() -> int:
    result = check_week08_gate()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["verdict"] == "GO" else 1


if __name__ == "__main__":
    raise SystemExit(main())
