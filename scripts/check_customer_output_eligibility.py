from __future__ import annotations

import argparse
import json

from _bootstrap import ROOT as _ROOT  # noqa: F401

from cloud_expert.evidence_packages.builder import make_session
from cloud_expert.evidence_packages.validation import (
    customer_output_eligibility,
    customer_output_eligibility_summary,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--package-code")
    args = parser.parse_args()
    with make_session() as session:
        result = (
            customer_output_eligibility(session, args.package_code)
            if args.package_code
            else customer_output_eligibility_summary(session)
        )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
