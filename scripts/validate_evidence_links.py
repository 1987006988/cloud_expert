import argparse
import json

import _bootstrap  # noqa: F401

from cloud_expert.database.session import SessionLocal
from cloud_expert.quality.evidence_checks import count_missing_evidence_links


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate parsed evidence links.")
    parser.add_argument("--provider", default=None)
    args = parser.parse_args()

    with SessionLocal() as session:
        missing = count_missing_evidence_links(session)
    result = {
        "provider": args.provider,
        "missing_evidence_links": missing,
        "errors": missing,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 1 if missing else 0


if __name__ == "__main__":
    raise SystemExit(main())
