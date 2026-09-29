from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import cast

from sqlalchemy.orm import Session

from cloud_expert.database.enums import MappingCandidateStatus, MappingLevel, ReviewStatus
from cloud_expert.database.models.mapping import MappingCandidate
from cloud_expert.database.models.product import Product
from cloud_expert.mapping.pipeline import _ensure_rule_sets, _market_rule_set, _upsert_candidate
from tests.fixtures.synthetic_data import load_synthetic_fixture


def test_rule_set_follows_both_product_markets(session: Session) -> None:
    fixture = load_synthetic_fixture(session)
    source = cast(Product, fixture["product"])
    target = cast(Product, fixture["competitor_product"])
    rules = _ensure_rule_sets(session, datetime.now(UTC))

    assert len(rules) == 12
    assert _market_rule_set(rules, "week07_product", source, target).market_mode == "cross_market"
    target.market_mode = "domestic"
    assert _market_rule_set(rules, "week07_product", source, target).market_mode == "domestic"
    source.market_mode = "international"
    target.market_mode = "international"
    assert _market_rule_set(rules, "week07_product", source, target).market_mode == "international"


def test_generation_keeps_terminal_candidate_and_idempotent_active_candidate(
    session: Session,
) -> None:
    fixture = load_synthetic_fixture(session)
    source = cast(Product, fixture["product"])
    target = cast(Product, fixture["competitor_product"])
    now = datetime.now(UTC)
    rules = _ensure_rule_sets(session, now)
    rule = rules["week07_product"]

    def generate(at: datetime, explanation: str) -> MappingCandidate:
        return _upsert_candidate(
            session=session,
            rule_set=rule,
            mapping_level=MappingLevel.PRODUCT.value,
            source_provider_id=source.provider_id,
            source_entity_type="product",
            source_entity_id=source.id,
            target_provider_id=target.provider_id,
            target_entity_type="product",
            target_entity_id=target.id,
            relationship_type="same_service_class",
            candidate_status=MappingCandidateStatus.CANDIDATE.value,
            raw_score=Decimal("90"),
            normalized_score=Decimal("0.9"),
            confidence=Decimal("0.85"),
            blocking_reasons=[],
            conditions=[],
            explanation=explanation,
            now=at,
        )

    candidate = generate(now, "synthetic initial")
    candidate_id = candidate.id
    generated_at = candidate.generated_at
    same = generate(now + timedelta(days=1), "synthetic initial")
    assert same.id == candidate_id
    assert same.generated_at == generated_at

    changed = generate(now + timedelta(days=2), "synthetic changed")
    assert changed.explanation == "synthetic changed"
    assert changed.generated_at != generated_at

    changed.candidate_status = MappingCandidateStatus.REJECTED.value
    changed.review_status = ReviewStatus.REJECTED.value
    terminal_time = changed.generated_at
    retained = generate(now + timedelta(days=3), "synthetic overwritten")
    assert retained.id == candidate_id
    assert retained.candidate_status == MappingCandidateStatus.REJECTED.value
    assert retained.explanation == "synthetic changed"
    assert retained.generated_at == terminal_time
