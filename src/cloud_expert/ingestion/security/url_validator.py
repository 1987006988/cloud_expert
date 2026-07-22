import ipaddress
import socket
from urllib.parse import urlparse

from cloud_expert.config.settings import get_settings
from cloud_expert.ingestion.exceptions import DomainNotAllowedError

BLOCKED_NETWORKS = tuple(
    ipaddress.ip_network(network)
    for network in (
        "127.0.0.0/8",
        "10.0.0.0/8",
        "172.16.0.0/12",
        "192.168.0.0/16",
        "169.254.0.0/16",
        "100.64.0.0/10",
        "::1/128",
        "fc00::/7",
        "fe80::/10",
    )
)

BLOCKED_HOSTNAMES = {"localhost", "metadata.google.internal"}
BLOCKED_IPS = {"169.254.169.254"}
ALLOWED_PORTS = {80, 443}


def _is_blocked_ip(ip_value: str) -> bool:
    try:
        address = ipaddress.ip_address(ip_value)
    except ValueError:
        return False
    return any(address in network for network in BLOCKED_NETWORKS) or ip_value in BLOCKED_IPS


def _assert_safe_host(hostname: str, *, allow_localhost_for_tests: bool) -> None:
    normalized = hostname.strip(".").lower()
    if normalized in BLOCKED_HOSTNAMES and not allow_localhost_for_tests:
        msg = f"blocked local hostname: {hostname}"
        raise DomainNotAllowedError(msg)
    if _is_blocked_ip(normalized) and not allow_localhost_for_tests:
        msg = f"blocked private or metadata IP: {hostname}"
        raise DomainNotAllowedError(msg)


def validate_fetch_url(
    url: str,
    *,
    allow_localhost_for_tests: bool | None = None,
    resolve_dns: bool = False,
) -> str:
    settings = get_settings()
    allow_localhost = (
        settings.allow_localhost_for_tests
        if allow_localhost_for_tests is None
        else allow_localhost_for_tests
    )
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        msg = f"unsupported URL scheme: {parsed.scheme}"
        raise DomainNotAllowedError(msg)
    hostname = parsed.hostname
    if not hostname:
        msg = "URL must include a hostname"
        raise DomainNotAllowedError(msg)
    if parsed.username or parsed.password:
        msg = "URL username and password are not allowed"
        raise DomainNotAllowedError(msg)
    if parsed.port is not None and parsed.port not in ALLOWED_PORTS and not allow_localhost:
        msg = f"dangerous or non-standard port is not allowed: {parsed.port}"
        raise DomainNotAllowedError(msg)

    _assert_safe_host(hostname, allow_localhost_for_tests=allow_localhost)

    if resolve_dns:
        for result in socket.getaddrinfo(hostname, None):
            address = result[4][0]
            if isinstance(address, str):
                _assert_safe_host(address, allow_localhost_for_tests=allow_localhost)

    return url
