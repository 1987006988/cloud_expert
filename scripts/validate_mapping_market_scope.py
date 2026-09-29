from __future__ import annotations

import json

import _bootstrap  # noqa: F401

from cloud_expert.database.session import SessionLocal
from cloud_expert.market.mapping_integrity import scan_mapping_market_integrity


def main() -> int:
    with SessionLocal() as session:
        result = scan_mapping_market_integrity(session)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
