from __future__ import annotations

from datetime import UTC, datetime

from cloud_expert.database.enums import FreshnessStatus
from cloud_expert.database.models.pricing import PriceSnapshot


def price_snapshot_freshness(snapshot: PriceSnapshot | None, *, now: datetime | None = None) -> str:
    if snapshot is None or snapshot.captured_at is None:
        return FreshnessStatus.UNKNOWN.value
    current = now or datetime.now(UTC)
    captured = snapshot.captured_at
    if captured.tzinfo is None:
        captured = captured.replace(tzinfo=UTC)
    effective_to = snapshot.effective_to
    if effective_to is not None:
        if effective_to.tzinfo is None:
            effective_to = effective_to.replace(tzinfo=UTC)
        if effective_to < current:
            return FreshnessStatus.HISTORICAL.value
    age_days = (current - captured).total_seconds() / 86400
    if age_days < 0:
        return FreshnessStatus.UNKNOWN.value
    effective_from = snapshot.effective_from
    if effective_from is not None:
        if effective_from.tzinfo is None:
            effective_from = effective_from.replace(tzinfo=UTC)
        if effective_from > current:
            return FreshnessStatus.UNKNOWN.value
    if age_days > 14:
        return FreshnessStatus.STALE.value
    if age_days > 11:
        return FreshnessStatus.DUE_SOON.value
    return FreshnessStatus.FRESH.value
