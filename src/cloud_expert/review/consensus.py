from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

MODEL = "gpt-6-astra"
VERDICTS = {
    "approve_internal",
    "approve_with_conditions",
    "reject",
    "defer",
    "reparse_required",
    "insufficient_evidence",
}
NON_APPROVABLE_PRECHECK = {
    "reject",
    "insufficient_evidence",
    "insufficient_data",
    "reparse_required",
    "internal_research_only",
    "requires_source_verification",
    "accept_internal_limitation",
}


@dataclass(frozen=True)
class ReviewOpinion:
    subject_type: str
    subject_id: int
    input_hash: str
    verdict: str
    reason_code: str
    rationale: str
    evidence_ids: tuple[int, ...]
    conditions: tuple[str, ...] = ()

    @property
    def key(self) -> tuple[str, int]:
        return self.subject_type, self.subject_id


@dataclass(frozen=True)
class Arbitration:
    verdict: str
    reason_code: str
    rationale: str
    evidence_ids: tuple[int, ...]
    conditions: tuple[str, ...]


def parse_opinion(payload: dict[str, Any]) -> ReviewOpinion:
    required = {
        "subject_type",
        "subject_id",
        "input_hash",
        "verdict",
        "reason_code",
        "rationale",
        "evidence_ids",
    }
    if missing := required - payload.keys():
        raise ValueError(f"missing review fields: {sorted(missing)}")
    if payload["verdict"] not in VERDICTS:
        raise ValueError(f"unsupported verdict: {payload['verdict']}")
    if not isinstance(payload["subject_id"], int) or payload["subject_id"] <= 0:
        raise ValueError("subject_id must be a positive integer")
    if not isinstance(payload["input_hash"], str) or len(payload["input_hash"]) != 64:
        raise ValueError("input_hash must be SHA-256")
    for field in ("subject_type", "reason_code", "rationale"):
        if not isinstance(payload[field], str) or not payload[field].strip():
            raise ValueError(f"{field} must be nonempty")
    evidence_ids = payload["evidence_ids"]
    conditions = payload.get("conditions", [])
    if not isinstance(evidence_ids, list) or any(
        not isinstance(item, int) or item <= 0 for item in evidence_ids
    ):
        raise ValueError("evidence_ids must be positive integers")
    if not isinstance(conditions, list) or any(
        not isinstance(item, str) or not item.strip() for item in conditions
    ):
        raise ValueError("conditions must be nonempty strings")
    if payload["verdict"] == "approve_with_conditions" and not conditions:
        raise ValueError("conditional approval requires conditions")
    return ReviewOpinion(
        subject_type=payload["subject_type"],
        subject_id=payload["subject_id"],
        input_hash=payload["input_hash"],
        verdict=payload["verdict"],
        reason_code=payload["reason_code"],
        rationale=payload["rationale"],
        evidence_ids=tuple(sorted(set(evidence_ids))),
        conditions=tuple(conditions),
    )


def validate_manifest(payload: dict[str, Any], stage: str) -> list[ReviewOpinion]:
    if payload.get("schema_version") != "1.0" or payload.get("stage") != stage:
        raise ValueError("review manifest schema or stage mismatch")
    if payload.get("model") != MODEL:
        raise ValueError("review manifest must identify the approved highest-tier model")
    if (
        not isinstance(payload.get("review_session_id"), str)
        or not payload["review_session_id"].strip()
    ):
        raise ValueError("review_session_id is required")
    raw_items = payload.get("items")
    if not isinstance(raw_items, list):
        raise ValueError("items must be a list")
    items = [parse_opinion(item) for item in raw_items]
    if len({item.key for item in items}) != len(items):
        raise ValueError("duplicate subject in review manifest")
    return items


def arbitrate(
    precheck_verdict: str,
    precheck_input_hash: str,
    precheck_evidence_ids: tuple[int, ...],
    primary: ReviewOpinion | None,
    adversarial: ReviewOpinion | None,
) -> Arbitration:
    if primary is None or adversarial is None:
        return Arbitration(
            "defer", "review_stage_missing", "Both model reviews are required.", (), ()
        )
    if primary.key != adversarial.key:
        raise ValueError("review subject mismatch")
    if primary.input_hash != precheck_input_hash or adversarial.input_hash != precheck_input_hash:
        return Arbitration("defer", "stale_review_input", "Review input changed.", (), ())
    known_evidence = set(precheck_evidence_ids)
    if not set(primary.evidence_ids).issubset(known_evidence) or not set(
        adversarial.evidence_ids
    ).issubset(known_evidence):
        return Arbitration("defer", "unverified_evidence", "Review cites unknown evidence.", (), ())
    if "reparse_required" in {primary.verdict, adversarial.verdict}:
        return Arbitration("reparse_required", "reparse_requested", "Reparse requested.", (), ())
    if "reject" in {primary.verdict, adversarial.verdict}:
        return Arbitration("reject", "model_rejection", "At least one model rejected.", (), ())
    if precheck_verdict in NON_APPROVABLE_PRECHECK:
        return Arbitration(
            "defer",
            "precheck_blocked",
            f"Deterministic precheck remains {precheck_verdict}.",
            (),
            (),
        )
    if primary.verdict != adversarial.verdict:
        return Arbitration("defer", "model_disagreement", "Model verdicts differ.", (), ())
    if primary.verdict in {"defer", "insufficient_evidence"}:
        return Arbitration("defer", "model_deferred", "Model review did not approve.", (), ())
    if not primary.evidence_ids or not adversarial.evidence_ids:
        return Arbitration("defer", "uncited_approval", "Approval requires evidence IDs.", (), ())
    if primary.verdict == "approve_with_conditions":
        conditions = tuple(sorted(set(primary.conditions + adversarial.conditions)))
        return Arbitration(
            "approve_with_conditions",
            "dual_model_conditional_consensus",
            "Both independent models approved with recorded conditions.",
            tuple(sorted(set(primary.evidence_ids + adversarial.evidence_ids))),
            conditions,
        )
    return Arbitration(
        "approve_internal",
        "dual_model_internal_consensus",
        "Both independent models approved for internal use only.",
        tuple(sorted(set(primary.evidence_ids + adversarial.evidence_ids))),
        (),
    )


def fingerprint(payload: object) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")
    ).hexdigest()
