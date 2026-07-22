from urllib.parse import urlparse

from cloud_expert.ingestion.exceptions import DomainNotAllowedError


def normalize_hostname(hostname: str) -> str:
    return hostname.strip(".").lower()


def validate_allowed_domains(domains: list[str]) -> None:
    if not domains:
        msg = "allowed_domains must not be empty"
        raise DomainNotAllowedError(msg)
    for domain in domains:
        normalized = normalize_hostname(domain)
        if normalized in {"*", ""} or "*" in normalized:
            msg = "wildcard domains are not allowed"
            raise DomainNotAllowedError(msg)


def is_domain_allowed(hostname: str, allowed_domains: list[str], *, allow_subdomains: bool) -> bool:
    host = normalize_hostname(hostname)
    for domain in allowed_domains:
        allowed = normalize_hostname(domain)
        if host == allowed:
            return True
        if allow_subdomains and host.endswith(f".{allowed}"):
            return True
    return False


def assert_url_allowed_by_policy(
    url: str,
    allowed_domains: list[str],
    *,
    allow_subdomains: bool,
) -> None:
    validate_allowed_domains(allowed_domains)
    hostname = urlparse(url).hostname
    if hostname is None or not is_domain_allowed(
        hostname,
        allowed_domains,
        allow_subdomains=allow_subdomains,
    ):
        msg = f"URL host is not in allowed domains: {url}"
        raise DomainNotAllowedError(msg)
