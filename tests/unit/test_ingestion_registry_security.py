from pathlib import Path

import pytest
from pydantic import ValidationError

from cloud_expert.ingestion.exceptions import DomainNotAllowedError
from cloud_expert.ingestion.registry.loader import load_registry_entries
from cloud_expert.ingestion.registry.schemas import SourceRegistryEntry
from cloud_expert.ingestion.security.domain_policy import is_domain_allowed
from cloud_expert.ingestion.security.headers import sanitize_response_headers
from cloud_expert.ingestion.security.path_safety import ensure_relative_safe_path, safe_path_segment
from cloud_expert.ingestion.security.url_validator import validate_fetch_url


def test_source_registry_fixtures_validate() -> None:
    entries = load_registry_entries(Path("data/source_registry"))
    assert {entry.source_id for entry in entries} >= {
        "synthetic_html_fixture",
        "synthetic_json_fixture",
        "synthetic_pdf_fixture",
    }


def test_source_registry_rejects_authentication_with_automated_fetch() -> None:
    entry = load_registry_entries(Path("data/source_registry"))[0]
    data = entry.model_dump(exclude={"registry_file"})
    data["source_id"] = "synthetic_bad_auth"
    data["requires_authentication"] = True
    data["allow_automated_fetch"] = True
    with pytest.raises(ValidationError):
        SourceRegistryEntry.model_validate(data)


def test_domain_policy_requires_exact_or_allowed_subdomain() -> None:
    assert is_domain_allowed("example.invalid", ["example.invalid"], allow_subdomains=False)
    assert not is_domain_allowed("evil-example.invalid", ["example.invalid"], allow_subdomains=True)
    assert is_domain_allowed("docs.example.invalid", ["example.invalid"], allow_subdomains=True)


def test_url_validator_blocks_ssrf_and_dangerous_schemes() -> None:
    for url in (
        "file:///etc/passwd",
        "ftp://example.invalid/file",
        "http://127.0.0.1/private",
        "http://169.254.169.254/latest/meta-data",
        "http://user:pass@example.invalid/path",
        "http://example.invalid:22/path",
    ):
        with pytest.raises(DomainNotAllowedError):
            validate_fetch_url(url)


def test_path_safety_blocks_traversal_and_sanitizes_segments() -> None:
    assert safe_path_segment("Synthetic Source!") == "Synthetic_Source"
    with pytest.raises(ValueError):
        ensure_relative_safe_path("../outside")


def test_sensitive_headers_are_redacted() -> None:
    headers = sanitize_response_headers(
        {
            "Content-Type": "text/html",
            "Set-Cookie": "session=secret",
            "X-Api-Key": "secret",
            "ETag": "abc",
        }
    )
    assert headers["Content-Type"] == "text/html"
    assert headers["Set-Cookie"] == "[REDACTED]"
    assert headers["X-Api-Key"] == "[REDACTED]"
    assert headers["ETag"] == "abc"
