"""Explicit AWS policy dispatch for current use, separate from historical listing."""

from contextlib import nullcontext
from pathlib import Path

from sqlalchemy import inspect
from sqlalchemy.orm import Session, object_session

from cloud_expert.config.settings import get_settings
from cloud_expert.database.models.pricing import PriceSnapshot
from cloud_expert.pricing.aws_catalog_promotion import RULE as AWS_CATALOG_RULE
from cloud_expert.pricing.aws_catalog_promotion import aws_catalog_price_valid
from cloud_expert.pricing.aws_document_catalog import RULE as AWS_DOCUMENT_RULE
from cloud_expert.pricing.aws_expired_history import expired_history_disposition
from cloud_expert.pricing.aws_price_replacement import SUPPORTED, aws_replacement_disposition
from cloud_expert.pricing.price_lifecycle import PriceDisposition
from cloud_expert.pricing.price_quarantine import quarantine_disposition


def is_aws_price(snapshot: PriceSnapshot) -> bool:
    session = object_session(snapshot)
    with session.no_autoflush if session is not None else nullcontext():
        provider = snapshot.price_sku.provider
        rule = snapshot.evidence.parser_rule or ""
        return (provider is not None and provider.code == "aws") or rule.startswith("aws_")


def aws_price_current(session: Session, snapshot: PriceSnapshot) -> bool:
    """Unknown AWS derivations fail closed; adding a rule needs an explicit verifier."""
    if session.new or session.dirty or session.deleted:
        return False
    quarantine = quarantine_disposition(session, snapshot, Path(get_settings().raw_data_dir))
    if quarantine is not None:
        return False
    if (
        expired_history_disposition(session, snapshot, raw_root=Path(get_settings().raw_data_dir))
        is not None
    ):
        return False
    if not is_aws_price(snapshot):
        return False
    if snapshot.id in SUPPORTED or snapshot.evidence.parser_rule == AWS_DOCUMENT_RULE:
        return (
            aws_replacement_disposition(
                session, snapshot, raw_root=Path(get_settings().raw_data_dir)
            ).status
            == "current"
        )
    if snapshot.evidence.parser_rule != AWS_CATALOG_RULE:
        return False
    return aws_catalog_price_valid(session, snapshot, raw_root=Path(get_settings().raw_data_dir))


def aws_price_disposition(session: Session, snapshot: PriceSnapshot) -> PriceDisposition:
    """Classify persisted history without treating supersession as current eligibility."""
    if session.new or session.dirty or session.deleted:
        identity = inspect(snapshot).identity
        return PriceDisposition(
            price_id=int(identity[0]) if identity else 0,
            status="blocked",
            diagnostics=("clean_session_required",),
        )
    quarantine = quarantine_disposition(session, snapshot, Path(get_settings().raw_data_dir))
    if quarantine is not None:
        return quarantine
    expired = expired_history_disposition(
        session, snapshot, raw_root=Path(get_settings().raw_data_dir)
    )
    if expired is not None:
        return PriceDisposition.model_validate(expired.model_dump(mode="python"))
    if is_aws_price(snapshot) and (
        snapshot.id in SUPPORTED or snapshot.evidence.parser_rule == AWS_DOCUMENT_RULE
    ):
        return aws_replacement_disposition(
            session, snapshot, raw_root=Path(get_settings().raw_data_dir)
        )
    current = aws_price_current(session, snapshot)
    return PriceDisposition(
        price_id=snapshot.id,
        status="current" if current else "blocked",
        current_price_id=snapshot.id if current else None,
        diagnostics=() if current else ("unverified_aws_catalog_or_derivation",),
    )
