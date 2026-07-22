from sqlalchemy import select
from sqlalchemy.orm import Session

from cloud_expert.database.enums import EvidenceType
from cloud_expert.database.models.source import Evidence
from cloud_expert.parsing.models import FieldCandidate


def get_or_create_evidence(
    session: Session,
    *,
    source_document_id: int,
    snapshot_record_id: int | None,
    content_hash: str | None,
    page_title: str | None,
    candidate: FieldCandidate,
) -> tuple[Evidence, bool]:
    statement = select(Evidence).where(
        Evidence.source_document_id == source_document_id,
        Evidence.snapshot_record_id == snapshot_record_id,
        Evidence.locator == candidate.locator,
        Evidence.excerpt == candidate.excerpt,
        Evidence.parser_rule == candidate.parser_rule,
    )
    existing = session.scalar(statement)
    if existing is not None:
        return existing, False
    evidence = Evidence(
        source_document_id=source_document_id,
        snapshot_record_id=snapshot_record_id,
        page_title=page_title,
        section_title=candidate.section_title,
        locator=candidate.locator,
        excerpt=candidate.excerpt[:4000],
        evidence_type=EvidenceType.HTML_SECTION.value,
        content_hash=content_hash,
        parser_rule=candidate.parser_rule,
        confidence=candidate.confidence,
        review_status=candidate.review_status,
    )
    session.add(evidence)
    session.flush()
    return evidence, True
