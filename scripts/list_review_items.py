import argparse
import json
from pathlib import Path

import _bootstrap  # noqa: F401
from sqlalchemy import select

from cloud_expert.database.models.review import ReviewItem
from cloud_expert.database.session import SessionLocal
from cloud_expert.ingestion.storage.atomic_write import atomic_write_text


def main() -> int:
    parser = argparse.ArgumentParser(description="List review queue items.")
    parser.add_argument("--provider", default=None)
    parser.add_argument("--product", default=None)
    parser.add_argument("--status", default=None)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()

    statement = select(ReviewItem)
    if args.provider:
        statement = statement.where(ReviewItem.provider_code == args.provider)
    if args.product:
        statement = statement.where(ReviewItem.product_code == args.product)
    if args.status:
        statement = statement.where(ReviewItem.status == args.status)
    with SessionLocal() as session:
        rows = session.scalars(statement.order_by(ReviewItem.created_at.desc())).all()
        payload = [
            {
                "id": row.id,
                "item_type": row.item_type,
                "severity": row.severity,
                "status": row.status,
                "provider_code": row.provider_code,
                "product_code": row.product_code,
                "field_code": row.field_code,
                "reason": row.reason,
            }
            for row in rows
        ]
    output = json.dumps(payload, ensure_ascii=False, indent=2, default=str)
    if args.output:
        atomic_write_text(args.output, output)
        print(json.dumps({"output": str(args.output), "items": len(payload)}, indent=2))
    else:
        print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
