class IngestionError(Exception):
    error_code = "unknown"


class ConfigurationError(IngestionError):
    error_code = "configuration_error"


class DomainNotAllowedError(IngestionError):
    error_code = "domain_not_allowed"


class RedirectViolationError(IngestionError):
    error_code = "redirect_violation"


class RequiresAuthenticationError(IngestionError):
    error_code = "requires_authentication"


class RequiresBrowserError(IngestionError):
    error_code = "requires_browser"


class MimeMismatchError(IngestionError):
    error_code = "mime_mismatch"


class FileTooLargeError(IngestionError):
    error_code = "file_too_large"


class EmptyContentError(IngestionError):
    error_code = "empty_content"


class StorageFailureError(IngestionError):
    error_code = "storage_failure"


class HttpStatusError(IngestionError):
    error_code = "http_error"


class TimeoutIngestionError(IngestionError):
    error_code = "timeout"


class SSLIngestionError(IngestionError):
    error_code = "ssl_failure"


class DNSIngestionError(IngestionError):
    error_code = "dns_failure"
