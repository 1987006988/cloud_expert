from sqlalchemy import func, select
from sqlalchemy.orm import Session

from cloud_expert.database.enums import ReviewStatus
from cloud_expert.database.models.parsing import ParsedFieldCandidate
from cloud_expert.database.models.review import ReviewItem


def count_low_confidence_fields(session: Session, provider_code: str, product_code: str) -> int:
    return int(
        session.scalar(
            select(func.count())
            .select_from(ParsedFieldCandidate)
            .join(ReviewItem, ReviewItem.parsed_field_candidate_id == ParsedFieldCandidate.id)
            .where(
                ReviewItem.provider_code == provider_code,
                ReviewItem.product_code == product_code,
                ParsedFieldCandidate.review_status == ReviewStatus.PENDING_REVIEW.value,
            )
        )
        or 0
    )
