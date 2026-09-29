from __future__ import annotations

import json
from pathlib import Path

import _bootstrap  # noqa: F401

from cloud_expert.database.session import SessionLocal
from cloud_expert.market.validation import scan_market_integrity

OUTPUT = Path("reports") / "market"


def main() -> int:
    with SessionLocal() as session:
        result = scan_market_integrity(session)
    OUTPUT.mkdir(parents=True, exist_ok=True)
    (OUTPUT / "market_results.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    lines = ["# Cross-Market Contamination", "", "| Check | Count |", "| --- | ---: |"]
    lines.extend(f"| {key} | {value} |" for key, value in result["counts"].items())
    lines.extend(
        [
            "",
            f"Customer exposure detected: `{result['customer_exposure_detected']}`",
            f"Internal remediation required: `{result['internal_remediation_required']}`",
            "",
            "Counts are conservative checks on recorded relationships; unknown scope is not inferred from URL or language.",
        ]
    )
    (OUTPUT / "cross_market_contamination.md").write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 1 if result["customer_exposure_detected"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
