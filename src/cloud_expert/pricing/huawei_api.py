"""Read-only on-demand pricing query; no order or resource operations exist here."""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator, model_validator

ENDPOINT = "https://bss.myhuaweicloud.com/v2/bills/ratings/on-demand-resources"
DOCUMENTATION = "https://support.huaweicloud.com/api-oce/bcloud_01001.html"
MAX_RESPONSE_BYTES = 2_097_152


class PricingQueryError(ValueError):
    """A safe message which does not contain credentials or response bodies."""


class ProductQuery(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    id: str = Field(min_length=1, max_length=64, pattern=r"^[\w.-]+$")
    cloud_service_type: str = Field(min_length=1, max_length=400, pattern=r"^[\w.-]+$")
    resource_type: str = Field(min_length=1, max_length=400, pattern=r"^[\w.-]+$")
    resource_spec: str = Field(min_length=1, max_length=400, pattern=r"^[\w.-]+$")
    region: str = Field(min_length=1, max_length=64, pattern=r"^cn-[a-z]+-\d+$")
    usage_factor: str = Field(min_length=1, max_length=64, pattern=r"^[\w.-]+$")
    usage_value: float = Field(gt=0, allow_inf_nan=False)
    usage_measure_id: int = Field(ge=1, le=9999)
    subscription_num: int = Field(ge=1, le=10000)
    available_zone: str | None = Field(default=None, max_length=64, pattern=r"^[\w.-]+$")
    resource_size: int | None = Field(default=None, ge=1, le=214783647)
    size_measure_id: int | None = Field(default=None, ge=1, le=9999)


class PricingQuery(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    product_infos: list[ProductQuery] = Field(min_length=1, max_length=100)
    inquiry_precision: int = Field(default=1, ge=0, le=1)

    @model_validator(mode="after")
    def unique_ids(self) -> PricingQuery:
        if len({row.id for row in self.product_infos}) != len(self.product_infos):
            raise ValueError("query IDs must be unique")
        return self


class LocalCredentials(BaseModel):
    model_config = ConfigDict(extra="forbid")

    token: SecretStr
    project_id: SecretStr

    @field_validator("token", "project_id")
    @classmethod
    def validate_secret(cls, value: SecretStr) -> SecretStr:
        raw = value.get_secret_value()
        if not raw.strip() or any(char.isspace() for char in raw):
            raise ValueError("local credential is empty or contains whitespace")
        return value


def credential_status() -> dict[str, bool]:
    return {
        name: bool(os.environ.get(name, "").strip())
        for name in ("HUAWEICLOUD_AUTH_TOKEN", "HUAWEICLOUD_PROJECT_ID")
    }


def query_prices(query: PricingQuery, credentials: LocalCredentials) -> bytes:
    body = query.model_dump(exclude_none=True)
    body["project_id"] = credentials.project_id.get_secret_value()
    # Disallow redirects/proxy environment inheritance so tokens only reach this endpoint.
    try:
        with (
            httpx.Client(timeout=30, follow_redirects=False, trust_env=False) as client,
            client.stream(
                "POST",
                ENDPOINT,
                json=body,
                headers={"X-Auth-Token": credentials.token.get_secret_value()},
            ) as response,
        ):
            if response.status_code != 200:
                raise PricingQueryError(f"Official pricing API HTTP {response.status_code}")
            chunks = bytearray()
            for chunk in response.iter_bytes():
                chunks.extend(chunk)
                if len(chunks) > MAX_RESPONSE_BYTES:
                    raise PricingQueryError("Official pricing response exceeded size limit")
    except httpx.HTTPError:
        raise PricingQueryError(
            "Official pricing API connection failed; no credentials logged"
        ) from None
    raw = bytes(chunks)
    validate_response(raw, query)
    return raw


def validate_response(raw: bytes, query: PricingQuery) -> None:
    try:
        payload = json.loads(raw)
        if not isinstance(payload, dict) or payload.get("error_code"):
            raise ValueError
        rows = payload["product_rating_results"]
        if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
            raise ValueError
        ids = [row["id"] for row in rows]
        if len(ids) != len(set(ids)) or set(ids) != {item.id for item in query.product_infos}:
            raise ValueError
        if payload.get("currency") not in ("CNY", "", None):
            raise ValueError
        from decimal import Decimal

        for row in rows:
            value = Decimal(str(row["official_website_amount"]))
            if row.get("measure_id") != 1 or not value.is_finite() or value < 0:
                raise ValueError
    except (ValueError, KeyError, TypeError, ArithmeticError):
        raise PricingQueryError(
            "Official pricing response failed schema/correlation validation"
        ) from None


def stage_response(raw: bytes, query: PricingQuery, root: Path) -> dict[str, Any]:
    """Keep the exact response locally; do not promote it into price evidence yet."""
    validate_response(raw, query)
    captured = datetime.now(UTC)
    digest = hashlib.sha256(raw).hexdigest()
    directory = root / f"{captured:%Y%m%dT%H%M%SZ}_{digest[:12]}_{uuid.uuid4().hex[:8]}"
    directory.mkdir(parents=True, exist_ok=False)
    with (directory / "response.bin").open("xb") as handle:
        handle.write(raw)
    metadata = {
        "endpoint": ENDPOINT,
        "documentation": DOCUMENTATION,
        "captured_at": captured.isoformat(),
        "response_sha256": digest,
        "query": query.model_dump(exclude_none=True),
        "classification": "local_account_scoped_response",
        "external_transfer_allowed": False,
        "promotion_status": "pending_source_document_and_evidence",
        "notes": "Response may contain account discounts; never include it in model prompts.",
    }
    with (directory / "metadata.json").open("x", encoding="utf-8") as handle:
        json.dump(metadata, handle, ensure_ascii=False, indent=2)
    return {
        "status": "staged_not_ingested",
        "directory": str(directory.resolve()),
        "response_sha256": digest,
        "products_received": len(query.product_infos),
        "database_written": False,
    }
