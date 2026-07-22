from datetime import datetime

from pydantic import field_validator

from cloud_expert.database.enums import AuthorityLevel, EvidenceType, ReviewStatus, SourceType
from cloud_expert.schemas.base import (
    ConfidenceMixin,
    ListResponse,
    ReadSchema,
    SchemaBase,
    validate_url,
)


class SourceDocumentBase(SchemaBase):
    provider_id: int
    source_type: SourceType
    title: str
    url: str
    language: str | None = None
    authority_level: AuthorityLevel
    published_at: datetime | None = None
    captured_at: datetime | None = None
    content_hash: str
    storage_path: str | None = None
    mime_type: str | None = None
    http_status: int | None = None
    is_current: bool = True

    @field_validator("url")
    @classmethod
    def _url(cls, value: str) -> str:
        checked = validate_url(value)
        assert checked is not None
        return checked


class SourceDocumentCreate(SourceDocumentBase):
    pass


class SourceDocumentUpdate(SchemaBase):
    title: str | None = None
    is_current: bool | None = None
    storage_path: str | None = None
    http_status: int | None = None


class SourceDocumentRead(SourceDocumentBase, ReadSchema):
    captured_at: datetime
    created_at: datetime


class SourceDocumentList(ListResponse):
    items: list[SourceDocumentRead]


class SourceDocumentFilter(SchemaBase):
    provider_id: int | None = None
    source_type: SourceType | None = None
    authority_level: AuthorityLevel | None = None
    is_current: bool | None = None


class EvidenceBase(ConfidenceMixin):
    source_document_id: int
    section_title: str | None = None
    locator: str
    excerpt: str
    evidence_type: EvidenceType
    review_status: ReviewStatus = ReviewStatus.PENDING_REVIEW
    reviewed_by: str | None = None
    reviewed_at: datetime | None = None


class EvidenceCreate(EvidenceBase):
    pass


class EvidenceUpdate(SchemaBase):
    section_title: str | None = None
    locator: str | None = None
    excerpt: str | None = None
    confidence: float | None = None
    review_status: ReviewStatus | None = None
    reviewed_by: str | None = None
    reviewed_at: datetime | None = None


class EvidenceRead(EvidenceBase, ReadSchema):
    created_at: datetime
    updated_at: datetime


class EvidenceList(ListResponse):
    items: list[EvidenceRead]


class EvidenceFilter(SchemaBase):
    source_document_id: int | None = None
    review_status: ReviewStatus | None = None
    evidence_type: EvidenceType | None = None
