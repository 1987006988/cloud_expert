import argparse
import json

import _bootstrap  # noqa: F401

from cloud_expert.database.session import SessionLocal
from cloud_expert.quality.partitions import count_partition_region_violations


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate provider cloud partition boundaries.")
    parser.add_argument("--provider", required=True)
    parser.add_argument("--partition", default=None)
    args = parser.parse_args()
    partition = args.partition or _default_partition(args.provider)

    with SessionLocal() as session:
        violations = count_partition_region_violations(
            session,
            provider_code=args.provider,
            partition_code=partition,
        )
    result = {
        "provider": args.provider,
        "partition": partition,
        "partition_region_violations": violations,
        "errors": violations,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 1 if violations else 0


def _default_partition(provider_code: str) -> str:
    if provider_code == "aliyun":
        return "aliyun_public_cn"
    return "aws"


if __name__ == "__main__":
    raise SystemExit(main())
