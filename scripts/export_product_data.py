import argparse
import json

import _bootstrap  # noqa: F401
from sqlalchemy import select

from cloud_expert.database.models.product import Product
from cloud_expert.database.session import SessionLocal


def main() -> int:
    parser = argparse.ArgumentParser(description="Export parsed product records.")
    parser.add_argument("--provider", default=None)
    parser.add_argument("--product", default=None)
    args = parser.parse_args()

    statement = select(Product)
    if args.product:
        statement = statement.where(Product.code == args.product)
    with SessionLocal() as session:
        products = session.scalars(statement.order_by(Product.code)).all()
        payload = [
            {
                "id": product.id,
                "code": product.code,
                "official_name": product.official_name,
                "display_name": product.display_name,
                "market_mode": product.market_mode,
                "official_url": product.official_url,
                "documentation_url": product.documentation_url,
                "last_verified_at": product.last_verified_at,
            }
            for product in products
        ]
    print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
