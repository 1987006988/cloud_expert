from __future__ import annotations

import csv
import hashlib
import json
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import _bootstrap  # noqa: F401
from sqlalchemy import select

from cloud_expert.database.models.canonical import ComparabilityAssessment
from cloud_expert.database.models.decision import CandidateDecisionResult
from cloud_expert.database.models.evidence_package import EvidencePackage
from cloud_expert.database.models.mapping import MappingCandidate, MappingCandidateEvidence
from cloud_expert.database.models.parsing import ParsedFieldCandidate
from cloud_expert.database.models.review import (
    ModelReviewFinding,
    ModelReviewRun,
    ReviewItem,
)
from cloud_expert.database.models.source import Evidence, SourceDocument
from cloud_expert.database.models.tco import TCOResult
from cloud_expert.database.session import SessionLocal

POLICY_VERSION = "week11_model_review_v1"
REVIEWER_MODEL = "codex_agent_evidence_rules"
REPORT_ROOT = Path("reports/remediation/week11_model_review")


@dataclass(frozen=True)
class Finding:
    subject_type: str
    subject_id: int
    verdict: str
    reason_code: str
    rationale: str
    evidence_ids: list[int]
    input_hash: str


def _hash(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _finding(
    subject_type: str,
    subject_id: int,
    verdict: str,
    reason_code: str,
    rationale: str,
    evidence_ids: list[int],
    inputs: dict[str, Any],
) -> Finding:
    return Finding(
        subject_type=subject_type,
        subject_id=subject_id,
        verdict=verdict,
        reason_code=reason_code,
        rationale=rationale,
        evidence_ids=sorted(set(evidence_ids)),
        input_hash=_hash(inputs),
    )


def _build_findings() -> list[Finding]:
    with SessionLocal() as session:
        candidates = list(session.scalars(select(MappingCandidate).order_by(MappingCandidate.id)))
        links = list(session.scalars(select(MappingCandidateEvidence)))
        packages = list(session.scalars(select(EvidencePackage)))
        evidence = {row.id: row for row in session.scalars(select(Evidence))}
        documents = {row.id: row for row in session.scalars(select(SourceDocument))}
        parsed = {row.id: row for row in session.scalars(select(ParsedFieldCandidate))}
        tco = {row.id: row for row in session.scalars(select(TCOResult))}
        review_items = list(
            session.scalars(
                select(ReviewItem).where(ReviewItem.status != "resolved").order_by(ReviewItem.id)
            )
        )
        assessments = list(
            session.scalars(
                select(ComparabilityAssessment)
                .where(ComparabilityAssessment.review_status == "pending_review")
                .order_by(ComparabilityAssessment.id)
            )
        )
        decisions = list(
            session.scalars(select(CandidateDecisionResult).order_by(CandidateDecisionResult.id))
        )

        links_by_candidate: dict[int, list[int]] = defaultdict(list)
        for link in links:
            links_by_candidate[link.mapping_candidate_id].append(link.evidence_id)
        package_by_candidate = {package.mapping_candidate_id: package for package in packages}
        candidate_by_id = {candidate.id: candidate for candidate in candidates}
        findings: list[Finding] = []

        for candidate in candidates:
            evidence_ids = sorted(set(links_by_candidate[candidate.id]))
            source_hashes = [
                documents[evidence[evidence_id].source_document_id].content_hash
                for evidence_id in evidence_ids
                if evidence_id in evidence and evidence[evidence_id].source_document_id in documents
            ]
            package = package_by_candidate.get(candidate.id)
            market_mode = candidate.rule_set.market_mode
            inputs: dict[str, Any] = {
                "status": candidate.candidate_status,
                "review_status": candidate.review_status,
                "market_mode": market_mode,
                "blocking_reasons": candidate.blocking_reasons,
                "evidence_ids": evidence_ids,
                "source_hashes": source_hashes,
                "package_hash": package.content_hash if package else None,
            }
            if (
                candidate.candidate_status in {"not_comparable", "rejected"}
                or candidate.blocking_reasons
            ):
                verdict, reason = "reject", "mapping_blocker"
                rationale = "Mapping has a not-comparable status or an explicit blocking reason."
            elif not evidence_ids or len(source_hashes) != len(evidence_ids) or package is None:
                verdict, reason = "insufficient_evidence", "mapping_provenance_incomplete"
                rationale = "Mapping evidence, source document, or evidence package is incomplete."
            elif market_mode == "cross_market":
                verdict, reason = "internal_research_only", "cross_market_mapping"
                rationale = "Evidence supports a research candidate across markets; it does not establish same-market customer eligibility."
            else:
                verdict, reason = "requires_human_confirmation", "customer_mapping_review_required"
                rationale = "Model checks cannot substitute for the named reviewer required for customer mapping approval."
            findings.append(
                _finding(
                    "mapping_candidate",
                    candidate.id,
                    verdict,
                    reason,
                    rationale,
                    evidence_ids,
                    inputs,
                )
            )

        for item in review_items:
            parsed_row = parsed.get(item.parsed_field_candidate_id or -1)
            evidence_row = evidence.get(item.evidence_id or -1)
            source = documents.get(evidence_row.source_document_id) if evidence_row else None
            inputs = {
                "status": item.status,
                "field_code": item.field_code,
                "raw_value": item.raw_value,
                "parsed_status": parsed_row.review_status if parsed_row else None,
                "evidence_id": item.evidence_id,
                "source_hash": source.content_hash if source else None,
            }
            if parsed_row and parsed_row.review_status == "rejected":
                verdict, reason = "reparse_required", "rejected_upstream_candidate"
                rationale = "The linked parsed candidate was rejected; retain this review item until corrected evidence is verified."
            elif source is None or evidence_row is None:
                verdict, reason = "insufficient_evidence", "source_chain_missing"
                rationale = "A complete Evidence and SourceDocument chain is required before accepting this field."
            else:
                verdict, reason = "requires_source_verification", "low_confidence_field"
                rationale = "Source-backed low-confidence extraction needs field-specific verification; no automatic fact approval was made."
            findings.append(
                _finding(
                    "review_item",
                    item.id,
                    verdict,
                    reason,
                    rationale,
                    [item.evidence_id] if item.evidence_id is not None else [],
                    inputs,
                )
            )

        for assessment in assessments:
            inputs = {
                "status": assessment.status,
                "reason_code": assessment.reason_code,
                "market_scope": assessment.market_scope,
                "review_status": assessment.review_status,
                "evidence_coverage_score": assessment.evidence_coverage_score,
            }
            if assessment.status in {"partial", "not_comparable"}:
                verdict, reason = "accept_internal_limitation", assessment.reason_code
                rationale = "Current comparability limitation is retained; missing evidence cannot be interpreted as a product weakness."
            else:
                verdict, reason = "requires_source_verification", assessment.reason_code
                rationale = "A pending assessment cannot become customer-facing without resolving its source, scope, and review conditions."
            findings.append(
                _finding(
                    "comparability_assessment",
                    assessment.id,
                    verdict,
                    reason,
                    rationale,
                    [],
                    inputs,
                )
            )

        for decision in decisions:
            mapped_candidate = candidate_by_id.get(decision.mapping_candidate_id or -1)
            package = package_by_candidate.get(decision.mapping_candidate_id or -1)
            tco_result = tco.get(decision.tco_result_id or -1)
            evidence_ids = (
                links_by_candidate.get(decision.mapping_candidate_id, [])
                if decision.mapping_candidate_id is not None
                else []
            )
            inputs = {
                "status": decision.decision_status,
                "review_status": decision.review_status,
                "output_level": decision.output_level,
                "mapping_candidate_id": decision.mapping_candidate_id,
                "mapping_market_mode": mapped_candidate.rule_set.market_mode
                if mapped_candidate
                else None,
                "package_hash": package.content_hash if package else None,
                "tco_status": tco_result.completeness_status if tco_result else None,
                "hard_block_count": decision.hard_block_count,
            }
            if decision.decision_status in {"blocked", "invalid_mapping"}:
                verdict, reason = "reject", decision.decision_status
                rationale = "A hard block or invalid mapping prevents a usable recommendation."
            elif decision.decision_status == "incomplete_cost":
                verdict, reason = "insufficient_data", "price_or_tco_incomplete"
                rationale = "The cost basis is incomplete; missing prices remain unknown and no customer recommendation is approved."
            elif mapped_candidate is None or package is None:
                verdict, reason = "insufficient_evidence", "mapping_or_package_missing"
                rationale = "The result lacks a complete mapping and evidence package."
            elif mapped_candidate.rule_set.market_mode == "cross_market":
                verdict, reason = "internal_research_only", "cross_market_decision"
                rationale = "Cross-market analysis is internal research and cannot be used as a same-market customer decision."
            else:
                verdict, reason = "requires_human_confirmation", "customer_decision_review_required"
                rationale = "Model checks do not grant customer decision approval."
            findings.append(
                _finding(
                    "candidate_decision_result",
                    decision.id,
                    verdict,
                    reason,
                    rationale,
                    evidence_ids,
                    inputs,
                )
            )

    return findings


def run_model_review() -> dict[str, Any]:
    findings = _build_findings()
    fingerprint = _hash(
        {
            "policy": POLICY_VERSION,
            "subjects": [(row.subject_type, row.subject_id, row.input_hash) for row in findings],
        }
    )
    run_code = f"model_review_{fingerprint[:16]}"
    counts = Counter((row.subject_type, row.verdict) for row in findings)
    summary: dict[str, Any] = {
        "run_code": run_code,
        "policy_version": POLICY_VERSION,
        "reviewer_model": REVIEWER_MODEL,
        "input_fingerprint": fingerprint,
        "findings": len(findings),
        "by_subject_and_verdict": {
            f"{subject}/{verdict}": count for (subject, verdict), count in sorted(counts.items())
        },
        "human_review_equivalent": False,
        "customer_eligibility_granted": False,
    }
    with SessionLocal() as session:
        existing = session.scalar(select(ModelReviewRun).where(ModelReviewRun.run_code == run_code))
        if existing is None:
            run = ModelReviewRun(
                run_code=run_code,
                policy_version=POLICY_VERSION,
                reviewer_model=REVIEWER_MODEL,
                input_fingerprint=fingerprint,
                reviewed_at=datetime.now(UTC),
                summary_json=summary,
            )
            session.add(run)
            session.flush()
            session.add_all(
                ModelReviewFinding(
                    run_id=run.id,
                    subject_type=row.subject_type,
                    subject_id=row.subject_id,
                    verdict=row.verdict,
                    reason_code=row.reason_code,
                    rationale=row.rationale,
                    evidence_ids=row.evidence_ids,
                    input_hash=row.input_hash,
                )
                for row in findings
            )
            session.commit()
            summary["already_recorded"] = False
        else:
            summary["already_recorded"] = True

    report_dir = REPORT_ROOT / run_code
    report_dir.mkdir(parents=True, exist_ok=True)
    (report_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    with (report_dir / "findings.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "subject_type",
                "subject_id",
                "verdict",
                "reason_code",
                "rationale",
                "evidence_ids",
                "input_hash",
            ]
        )
        for row in findings:
            writer.writerow(
                [
                    row.subject_type,
                    row.subject_id,
                    row.verdict,
                    row.reason_code,
                    row.rationale,
                    json.dumps(row.evidence_ids),
                    row.input_hash,
                ]
            )
    return summary


if __name__ == "__main__":
    print(json.dumps(run_model_review(), ensure_ascii=False, indent=2))
