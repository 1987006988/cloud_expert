import argparse
import json
from pathlib import Path

import _bootstrap  # noqa: F401

from cloud_expert.database.session import SessionLocal
from cloud_expert.parsing.pipeline import parse_registered_sources


def main() -> int:
    parser = argparse.ArgumentParser(description="Parse saved product source snapshots.")
    parser.add_argument("--provider", default=None)
    parser.add_argument("--product", default=None)
    parser.add_argument("--source-id", default=None)
    parser.add_argument("--registry-dir", type=Path, default=None)
    parser.add_argument("--raw-dir", type=Path, default=None)
    args = parser.parse_args()

    with SessionLocal() as session:
        summaries = parse_registered_sources(
            session,
            provider=args.provider,
            product=args.product,
            source_id=args.source_id,
            registry_dir=args.registry_dir,
            raw_dir=args.raw_dir,
        )
    print(
        json.dumps(
            [summary.model_dump() for summary in summaries],
            ensure_ascii=False,
            indent=2,
            default=str,
        )
    )
    return 1 if any(summary.status == "failed" for summary in summaries) else 0


if __name__ == "__main__":
    raise SystemExit(main())
