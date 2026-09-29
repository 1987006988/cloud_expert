from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from cloud_expert.database.models.mapping import (
    MappingCandidate,
    MappingCandidateEvidence,
    MappingRuleSet,
)
from cloud_expert.database.models.model_review_workflow import (
    ModelReviewAssignment,
    ModelReviewAuditEvent,
)
from cloud_expert.database.models.product import Product
from cloud_expert.database.models.review import ModelReviewFinding, ModelReviewRun
from cloud_expert.evidence_packages.builder import (
    _content_hash,
    _ensure_package,
    _ensure_package_items,
    _link_superseded_mapping_packages,
)
from cloud_expert.mapping.pipeline import _first_product_evidence
from cloud_expert.model_review.pilot import _fingerprint, mapping_review_input


def revise_product_mapping(session: Session, candidate_id: int) -> dict[str, Any]:
    old = session.get(MappingCandidate, candidate_id)
    if old is None or old.mapping_level != "product":
        raise ValueError("an existing product-level candidate is required")
    if old.superseded_by_id is not None:
        return {"status": "already_revised", "old_id": old.id, "new_id": old.superseded_by_id}
    if old.candidate_status in {"approved", "corrected", "rejected", "superseded"}:
        raise ValueError("terminal business decisions require a separate supersession review")
    source = session.get(Product, old.source_entity_id)
    target = session.get(Product, old.target_entity_id)
    if (
        source is None
        or target is None
        or source.market_mode != target.market_mode
        or old.rule_set.market_mode != source.market_mode
    ):
        raise ValueError("product revision requires validated same-market identities")
    evidence_ids = [
        value
        for p in (source, target)
        if (value := _first_product_evidence(session, p.id)) is not None
    ]
    if len(evidence_ids) != 2 or len(set(evidence_ids)) != 2:
        raise ValueError("both products require distinct current description Evidence")
    digest = _fingerprint({"old_id": old.id, "evidence_ids": evidence_ids})
    now = datetime.now(UTC)
    rule = MappingRuleSet(
        rule_set_code=old.rule_set.rule_set_code,
        rule_set_version=f"definition-evidence-{digest[:16]}",
        mapping_level=old.rule_set.mapping_level,
        category=old.rule_set.category,
        market_mode=old.rule_set.market_mode,
        description="Product definitions; does not establish SKU or performance equivalence.",
        required_fields=["product.description"],
        optional_fields=[],
        exclusion_rules=old.rule_set.exclusion_rules,
        scoring_config=old.rule_set.scoring_config,
        status=old.rule_set.status,
        effective_from=now,
    )
    session.add(rule)
    session.flush()
    new = MappingCandidate(
        rule_set_id=rule.id,
        mapping_level="product",
        source_provider_id=source.provider_id,
        source_entity_type="product",
        source_entity_id=source.id,
        target_provider_id=target.provider_id,
        target_entity_type="product",
        target_entity_id=target.id,
        relationship_type="same_service_class",
        candidate_status="candidate",
        raw_score=None,
        normalized_score=None,
        confidence=None,
        blocking_reasons=[],
        conditions=[
            "product-level service category only; no SKU, price, SLA or performance equivalence"
        ],
        explanation="The linked official product definitions support comparison at the service-category level only.",
        generated_at=now,
        valid_from=now,
        review_status="pending_review",
    )
    session.add(new)
    session.flush()
    for evidence_id in evidence_ids:
        session.add(
            MappingCandidateEvidence(
                mapping_candidate_id=new.id,
                evidence_id=evidence_id,
                evidence_role="category_positioning",
                created_at=now,
            )
        )
    session.flush()
    session.expire(new, ["evidence_links"])
    package, created = _ensure_package(session, new, now, _content_hash(session, new))
    if created:
        _ensure_package_items(session, package, new, now)
    links = sorted(new.evidence_links, key=lambda link: link.evidence_id)
    inputs = {
        "status": new.candidate_status,
        "review_status": new.review_status,
        "market_mode": new.rule_set.market_mode,
        "blocking_reasons": new.blocking_reasons,
        "evidence_ids": sorted(evidence_ids),
        "source_hashes": [link.evidence.source_document.content_hash for link in links],
        "package_hash": package.content_hash,
    }
    run = ModelReviewRun(
        run_code=f"mapping_revision_{digest[:16]}",
        policy_version="product_definition_precheck_v1",
        reviewer_model="deterministic_evidence_precheck",
        input_fingerprint=_fingerprint(inputs),
        reviewed_at=now,
        summary_json={"stage": "precheck", "findings": 1, "supersedes_candidate": old.id},
    )
    session.add(run)
    session.flush()
    finding = ModelReviewFinding(
        run_id=run.id,
        subject_type="mapping_candidate",
        subject_id=new.id,
        verdict="requires_dual_model_review",
        reason_code="repaired_product_definition_evidence",
        rationale="Current same-market product definitions require independent semantic review.",
        evidence_ids=sorted(evidence_ids),
        input_hash=_fingerprint(inputs),
    )
    session.add(finding)
    session.flush()
    assignment = ModelReviewAssignment(
        precheck_run_id=run.id,
        precheck_finding_id=finding.id,
        target_type="mapping_candidate",
        target_id=new.id,
        input_hash=finding.input_hash,
        prior_review_status="candidate",
        review_state="pending_model_review",
        evidence_ids=sorted(evidence_ids),
        updated_at=now,
    )
    session.add(assignment)
    session.flush()
    session.add(
        ModelReviewAuditEvent(
            assignment_id=assignment.id,
            event_code=f"revision_{digest[:24]}",
            previous_status=None,
            new_status="pending_model_review",
            source="deterministic_revision",
            model_id=None,
            reason="product_definition_evidence_repaired",
            affected_records=[{"old_id": old.id, "new_id": new.id, "evidence_ids": evidence_ids}],
            downstream_rebuild_required=True,
            timestamp=now,
        )
    )
    # Full raw-file provenance is verified before the old candidate is retired.
    mapping_review_input(session, run.run_code, new.id)
    for previous in session.scalars(
        select(ModelReviewAssignment).where(
            ModelReviewAssignment.target_type == "mapping_candidate",
            ModelReviewAssignment.target_id == old.id,
            ModelReviewAssignment.review_state != "superseded",
        )
    ):
        session.add(
            ModelReviewAuditEvent(
                assignment_id=previous.id,
                event_code=f"superseded_{digest[:24]}",
                previous_status=previous.review_state,
                new_status="superseded",
                source="deterministic_revision",
                model_id=None,
                reason="replaced_by_new_evidence_version",
                affected_records=[{"old_id": old.id, "new_id": new.id}],
                downstream_rebuild_required=True,
                timestamp=now,
            )
        )
        previous.review_state = "superseded"
        previous.updated_at = now
    old.candidate_status = "superseded"
    old.superseded_by_id = new.id
    old.valid_to = now
    session.flush()
    _link_superseded_mapping_packages(session)
    return {
        "status": "revised",
        "old_id": old.id,
        "new_id": new.id,
        "precheck_run_code": run.run_code,
        "assignment_id": assignment.id,
        "evidence_ids": evidence_ids,
        "package_id": package.id,
        "customer_eligible": False,
    }
