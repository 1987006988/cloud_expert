from cloud_expert.parsing.models import ParsedRecord


def obs_records_need_review(records: list[ParsedRecord]) -> bool:
    return any(
        field.review_status == "pending_review" for record in records for field in record.fields
    )
