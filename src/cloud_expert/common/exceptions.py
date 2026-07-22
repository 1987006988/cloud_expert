class CloudExpertError(Exception):
    """Base exception for project-specific errors."""


class NotFoundError(CloudExpertError):
    """Raised when a repository cannot find a requested record."""


class InvalidOperationError(CloudExpertError):
    """Raised when a repository operation is not valid for an entity."""
