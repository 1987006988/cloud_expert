# Object Storage Canonical Model

The object storage canonical model covers OBS/S3/OSS service-tier and
product-level facts extracted from official sources.

## Core Field Groups

| Group | Example canonical fields |
| --- | --- |
| Reliability | `object_storage.reliability.durability_percentage`, `object_storage.reliability.availability_percentage` |
| Billing | `object_storage.billing.minimum_storage_duration_days`, `object_storage.billing.minimum_billable_object_size_kib` |
| Limits | `object_storage.limits.max_object_size_gib`, `object_storage.limits.max_single_upload_size_gib` |
| Retrieval | `object_storage.retrieval.time_description` |
| Security | `object_storage.security.server_side_encryption_supported`, `object_storage.security.customer_managed_key_supported` |
| Protection | `object_storage.data_protection.cross_region_replication_supported`, `object_storage.data_protection.object_lock_supported` |
| Integration | `object_storage.integration.event_notification_supported` |
| Endpoints | `object_storage.endpoint.dual_stack_supported` |

## Week 6 Scope Limit

The prior `ProductSpecification` table does not preserve a direct
`service_tier_id`. The Week 6 normalization therefore records 90 object-storage
scope mismatch warnings where ideal `service_tier` scope had to fall back to
`product` scope. These rows remain evidence-backed, but not fully comparable.

