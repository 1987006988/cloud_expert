from __future__ import annotations

import argparse
import json

from _bootstrap import ROOT as _ROOT  # noqa: F401
from sqlalchemy import select

from cloud_expert.database.models.evidence_package import EvidencePackage
from cloud_expert.evidence_packages.builder import make_session
from cloud_expert.evidence_packages.render import package_payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--package-code", required=True)
    args = parser.parse_args()
    with make_session() as session:
        package = session.scalar(
            select(EvidencePackage).where(EvidencePackage.package_code == args.package_code)
        )
        if package is None:
            print(json.dumps({"error": "package_not_found"}))
            return 1
        payload = package_payload(package)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
