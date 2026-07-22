RETRYABLE_HTTP_STATUS = {408, 425, 429, 500, 502, 503, 504}
NON_RETRYABLE_HTTP_STATUS = {400, 401, 403, 404, 410}


def should_retry_http_status(status_code: int) -> bool:
    return status_code in RETRYABLE_HTTP_STATUS


def bounded_retry_count(max_retries: int) -> int:
    return max(0, min(max_retries, 5))
