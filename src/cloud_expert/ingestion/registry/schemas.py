from datetime import datetime
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from cloud_expert.database.enums import (
    AuthorityLevel,
    ComplianceReviewStatus,
    MarketMode,
    ReviewStatus,
    SourceType,
)
from cloud_expert.ingestion.exceptions import ConfigurationError
from cloud_expert.ingestion.security.domain_policy import (
    assert_url_allowed_by_policy,
    validate_allowed_domains,
)
from cloud_expert.ingestion.security.url_validator import validate_fetch_url

EXPECTED_CONTENT_TYPES = {
    "text/html",
    "application/json",
    "application/octet-stream",
    "application/pdf",
}
UPDATE_FREQUENCIES = {"manual", "daily", "weekly", "monthly", "quarterly"}
USER_AGENT_PROFILES = {"browser_compatible", "cloud_expert_bot", "test"}


class RegistrySchemaBase(BaseModel):
    model_config = ConfigDict(use_enum_values=True, extra="forbid")


class DomainPolicy(RegistrySchemaBase):
    allowed_domains: list[str] = Field(min_length=1)
    allow_subdomains: bool = False
    allow_redirects: bool = True
    allowed_redirect_domains: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_domains(self) -> "DomainPolicy":
        validate_allowed_domains(self.allowed_domains)
        if self.allowed_redirect_domains:
            validate_allowed_domains(self.allowed_redirect_domains)
        return self


class FetchPolicy(RegistrySchemaBase):
    timeout_seconds: int = Field(default=45, ge=1, le=120)
    connect_timeout_seconds: int = Field(default=10, ge=1, le=60)
    read_timeout_seconds: int = Field(default=30, ge=1, le=120)
    max_retries: int = Field(default=3, ge=0, le=5)
    retry_backoff_seconds: float = Field(default=1.0, ge=0, le=30)
    min_interval_seconds: float = Field(default=2.0, ge=0, le=60)
    max_content_length_bytes: int = Field(default=10_485_760, gt=0, le=52_428_800)
    user_agent_profile: str = "cloud_expert_bot"

    @field_validator("user_agent_profile")
    @classmethod
    def _profile(cls, value: str) -> str:
        if value not in USER_AGENT_PROFILES:
            msg = f"unsupported user_agent_profile: {value}"
            raise ValueError(msg)
        return value


class StoragePolicy(RegistrySchemaBase):
    keep_all_versions: bool = True
    deduplicate_identical_content: bool = True
    store_response_headers: bool = True
    store_request_headers: bool = False
    compression: Literal["none", "gzip"] = "none"
    retention_policy: str = "keep_all"

    @model_validator(mode="after")
    def _validate_storage(self) -> "StoragePolicy":
        if not self.keep_all_versions:
            msg = "raw source snapshots must keep all versions"
            raise ValueError(msg)
        if self.store_request_headers:
            msg = "request headers are not stored to avoid credentials"
            raise ValueError(msg)
        return self


class SourceSchedule(RegistrySchemaBase):
    update_frequency: str = "weekly"
    priority: int = Field(default=100, ge=0, le=1000)
    last_successful_fetch_at: datetime | None = None
    next_scheduled_fetch_at: datetime | None = None

    @field_validator("update_frequency")
    @classmethod
    def _frequency(cls, value: str) -> str:
        if value not in UPDATE_FREQUENCIES:
            msg = f"unsupported update_frequency: {value}"
            raise ValueError(msg)
        return value


class SourceRegistryEntry(RegistrySchemaBase):
    source_id: str = Field(min_length=3, max_length=128, pattern=r"^[a-z0-9][a-z0-9_-]*$")
    provider_code: str = Field(min_length=2, max_length=64)
    market_mode: MarketMode
    cloud_partition: str | None = Field(
        default=None,
        max_length=64,
        pattern=r"^[a-z0-9][a-z0-9_-]*$",
    )
    product_code: str | None = Field(default=None, max_length=128)
    source_type: SourceType
    title: str = Field(min_length=1, max_length=256)
    description: str | None = None
    language: str | None = None
    authority_level: AuthorityLevel
    url: str
    enabled: bool = True
    requires_authentication: bool = False
    requires_browser: bool = False
    allow_automated_fetch: bool = True
    expected_content_type: list[str] = Field(min_length=1)
    expected_file_extension: str | None = None
    expected_encoding: str | None = None
    content_selector: str | None = None
    metadata_selector: str | None = None
    domain_policy: DomainPolicy
    fetch_policy: FetchPolicy = Field(default_factory=FetchPolicy)
    storage_policy: StoragePolicy = Field(default_factory=StoragePolicy)
    schedule: SourceSchedule = Field(default_factory=SourceSchedule)
    owner: str | None = None
    review_status: ReviewStatus = ReviewStatus.PENDING_REVIEW
    reviewed_at: datetime | None = None
    robots_checked_at: datetime | None = None
    robots_allowed: bool | None = None
    terms_review_status: ComplianceReviewStatus = ComplianceReviewStatus.UNKNOWN
    automated_fetch_allowed: bool | None = None
    manual_only: bool = False
    compliance_notes: str | None = None
    notes: str | None = None
    fixture_response_path: str | None = None
    fixture_response_status: int = Field(default=200, ge=100, le=599)
    fixture_response_content_type: str | None = None
    registry_file: Path | None = None

    @field_validator("expected_content_type")
    @classmethod
    def _content_types(cls, values: list[str]) -> list[str]:
        normalized = [value.lower().split(";", 1)[0].strip() for value in values]
        unsupported = sorted(set(normalized) - EXPECTED_CONTENT_TYPES)
        if unsupported:
            msg = f"unsupported expected_content_type: {unsupported}"
            raise ValueError(msg)
        return normalized

    @model_validator(mode="after")
    def _validate_entry(self) -> "SourceRegistryEntry":
        validate_fetch_url(self.url)
        assert_url_allowed_by_policy(
            self.url,
            self.domain_policy.allowed_domains,
            allow_subdomains=self.domain_policy.allow_subdomains,
        )
        if self.requires_authentication and self.allow_automated_fetch:
            msg = "requires_authentication=true requires allow_automated_fetch=false"
            raise ValueError(msg)
        if self.requires_browser and self.allow_automated_fetch:
            msg = "requires_browser=true is not supported by Week 2 HTTP fetcher"
            raise ValueError(msg)
        if self.manual_only and self.allow_automated_fetch:
            msg = "manual_only sources cannot allow automated fetch"
            raise ValueError(msg)
        if (
            self.terms_review_status != ComplianceReviewStatus.APPROVED
            and not self.fixture_response_path
            and self.allow_automated_fetch
            and self.terms_review_status
            in {
                ComplianceReviewStatus.DISALLOWED,
                ComplianceReviewStatus.MANUAL_REVIEW_REQUIRED,
            }
        ):
            msg = "source terms do not allow automated fetch"
            raise ValueError(msg)
        if self.fixture_response_path is not None:
            host = urlparse(self.url).hostname or ""
            if not host.endswith(".invalid"):
                msg = "fixture_response_path is only allowed for .invalid fixture URLs"
                raise ValueError(msg)
        return self


class SourceValidationResult(RegistrySchemaBase):
    source_id: str | None = None
    file_path: str | None = None
    valid: bool
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    enabled: bool | None = None


def parse_registry_entry(
    data: dict[str, Any],
    *,
    registry_file: Path | None = None,
) -> SourceRegistryEntry:
    try:
        entry = SourceRegistryEntry.model_validate(data)
    except Exception as exc:
        raise ConfigurationError(str(exc)) from exc
    return entry.model_copy(update={"registry_file": registry_file})
