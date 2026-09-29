from cloud_expert.ingestion.registry.loader import get_entry_by_source_id
from cloud_expert.pricing.source_policy import approved_collection, collection_mode


def test_retired_source_is_not_approved_or_collectable():
    entry = get_entry_by_source_id("huawei_cloud_obs_pricing")
    assert collection_mode(entry) == "retired_no_collection"
    assert not approved_collection(entry)
    for attribute in ("enabled", "allow_automated_fetch", "automated_fetch_allowed", "manual_only"):
        changed = entry.model_copy(update={attribute: True})
        assert collection_mode(changed) != "retired_no_collection"
        assert not approved_collection(changed)


def test_approved_manual_api_replaces_collection_not_price_approval():
    for source_id in (
        "huawei_cloud_ecs_pricing_api_cn_north_4_c6_large_2",
        "huawei_cloud_obs_pricing_api_cn_north_4",
    ):
        entry = get_entry_by_source_id(source_id)
        assert approved_collection(entry)
        assert collection_mode(entry) == "manual_or_browser_snapshot_required"
        assert not entry.enabled and not entry.allow_automated_fetch
        assert entry.review_status != "approved"
        entry.terms_review_status = "pending_review"
        assert not approved_collection(entry)


def test_pending_or_misconfigured_source_is_not_silently_retired():
    entry = get_entry_by_source_id("huawei_cloud_obs_pricing")
    entry.terms_review_status = "pending_review"
    assert collection_mode(entry) == "blocked_or_misconfigured"
    assert not approved_collection(entry)
    entry.terms_review_status = "approved"
    assert not approved_collection(entry)
