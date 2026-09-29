"""Pricing collection readiness, including retained but retired sources."""

from cloud_expert.ingestion.registry.schemas import SourceRegistryEntry


def collection_mode(entry: SourceRegistryEntry) -> str:
    if (
        entry.terms_review_status == "disallowed"
        and not entry.enabled
        and not entry.allow_automated_fetch
        and not entry.automated_fetch_allowed
        and not entry.manual_only
    ):
        return "retired_no_collection"
    if entry.enabled and entry.allow_automated_fetch and not entry.manual_only:
        return "automated_http_snapshot"
    if entry.manual_only and not entry.enabled and not entry.allow_automated_fetch:
        return "manual_or_browser_snapshot_required"
    return "blocked_or_misconfigured"


def approved_collection(entry: SourceRegistryEntry) -> bool:
    return entry.terms_review_status == "approved" and collection_mode(entry) in {
        "automated_http_snapshot",
        "manual_or_browser_snapshot_required",
    }
