from __future__ import annotations

import argparse

from _bootstrap import ROOT

from cloud_expert.evidence_packages.builder import make_session
from cloud_expert.evidence_packages.render import export_package


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--package-code", required=True)
    parser.add_argument("--format", choices=["markdown", "json"], required=True)
    args = parser.parse_args()
    suffix = "md" if args.format == "markdown" else "json"
    output = ROOT / "reports" / "evidence_packages" / f"{args.package_code}.{suffix}"
    with make_session() as session:
        ok = export_package(
            session, args.package_code, output, "json" if suffix == "json" else "markdown"
        )
    print(f"exported={ok} output={output}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
