from datetime import UTC, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

FieldValue = str | int | float | bool | Decimal | None


class FieldCandidate(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    field_code: str
    raw_value: FieldValue
    raw_unit: str | None = None
    normalized_value: FieldValue = None
    canonical_unit: str | None = None
    locator: str
    excerpt: str
    confidence: float = Field(ge=0, le=1)
    review_status: str
    parser_rule: str
    target_table: str
    target_identity: str
    section_title: str | None = None

    def value_as_text(self) -> str:
        return "" if self.raw_value is None else str(self.raw_value)


class ParsedRecord(BaseModel):
    record_type: str
    source_id: str
    snapshot_id: str
    target_identity: str
    fields: list[FieldCandidate] = Field(default_factory=list)
    parser_version: str
    parsed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ParseSummary(BaseModel):
    source_id: str
    product_code: str
    status: Literal["succeeded", "unchanged", "failed", "partial", "skipped"]
    records_found: int = 0
    fields_found: int = 0
    evidence_created: int = 0
    review_items_created: int = 0
    parsing_run_id: int | None = None
    error_message: str | None = None
