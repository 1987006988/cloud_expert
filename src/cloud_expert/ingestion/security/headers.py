SENSITIVE_HEADER_NAMES = {
    "authorization",
    "proxy-authorization",
    "cookie",
    "set-cookie",
    "x-api-key",
    "x-auth-token",
    "x-amz-security-token",
}
SENSITIVE_HEADER_KEYWORDS = ("token", "secret", "key", "credential")

SAFE_HEADER_NAMES = {
    "content-type",
    "content-length",
    "etag",
    "last-modified",
    "cache-control",
    "date",
    "server",
    "location",
    "content-encoding",
    "accept-ranges",
}


def sanitize_response_headers(headers: dict[str, str]) -> dict[str, str]:
    sanitized: dict[str, str] = {}
    for name, value in headers.items():
        lower_name = name.lower()
        if lower_name in SENSITIVE_HEADER_NAMES or any(
            keyword in lower_name for keyword in SENSITIVE_HEADER_KEYWORDS
        ):
            sanitized[name] = "[REDACTED]"
        elif lower_name in SAFE_HEADER_NAMES:
            sanitized[name] = value
    return sanitized
