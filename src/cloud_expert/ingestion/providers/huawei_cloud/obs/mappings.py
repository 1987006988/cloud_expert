OBS_SPEC_DEFINITIONS = {
    "object_storage.durability_percentage": ("Durability percentage", "numeric", "percent"),
    "object_storage.availability_percentage": ("Availability percentage", "numeric", "percent"),
    "object_storage.max_object_size_gib": ("Maximum object size", "numeric", "GiB"),
    "object_storage.max_single_upload_size_gib": ("Maximum single upload size", "numeric", "GiB"),
    "object_storage.multipart_upload_supported": ("Multipart upload supported", "boolean", None),
    "object_storage.versioning_supported": ("Versioning supported", "boolean", None),
    "object_storage.lifecycle_management_supported": (
        "Lifecycle management supported",
        "boolean",
        None,
    ),
    "object_storage.cross_region_replication_supported": (
        "Cross-region replication supported",
        "boolean",
        None,
    ),
    "object_storage.server_side_encryption_supported": (
        "Server-side encryption supported",
        "boolean",
        None,
    ),
    "object_storage.customer_managed_key_supported": (
        "Customer-managed key supported",
        "boolean",
        None,
    ),
    "object_storage.static_website_hosting_supported": (
        "Static website hosting supported",
        "boolean",
        None,
    ),
    "object_storage.event_notification_supported": (
        "Event notification supported",
        "boolean",
        None,
    ),
    "object_storage.object_lock_supported": ("Object lock supported", "boolean", None),
    "object_storage.minimum_storage_duration_days": ("Minimum storage duration", "numeric", "day"),
    "object_storage.retrieval_time_description": ("Retrieval time description", "text", None),
}
