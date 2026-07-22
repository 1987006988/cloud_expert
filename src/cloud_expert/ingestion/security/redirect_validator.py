from urllib.parse import urljoin

from cloud_expert.ingestion.exceptions import RedirectViolationError
from cloud_expert.ingestion.registry.schemas import DomainPolicy
from cloud_expert.ingestion.security.domain_policy import assert_url_allowed_by_policy
from cloud_expert.ingestion.security.url_validator import validate_fetch_url


def validate_redirect_location(current_url: str, location: str, policy: DomainPolicy) -> str:
    if not policy.allow_redirects:
        msg = "redirects are disabled for this source"
        raise RedirectViolationError(msg)
    target_url = urljoin(current_url, location)
    try:
        validate_fetch_url(target_url)
        assert_url_allowed_by_policy(
            target_url,
            policy.allowed_redirect_domains or policy.allowed_domains,
            allow_subdomains=policy.allow_subdomains,
        )
    except Exception as exc:
        raise RedirectViolationError(str(exc)) from exc
    return target_url
