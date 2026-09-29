from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path
from typing import Any

import _bootstrap  # noqa: F401
from check_week12_gate import check_week12_gate

ROOT = Path(__file__).resolve().parents[1]


def check_week13_gate() -> dict[str, Any]:
    week12 = check_week12_gate()
    blockers = [] if week12["verdict"] == "GO" else ["W13-B001-week12-gate"]
    return {
        "gate": "WEEK13_GATE",
        "verdict": "GO" if not blockers else "NO-GO",
        "week11_gate": week12["week11_gate"],
        "week12_gate": week12["verdict"],
        "week12_blockers": week12["blocking_items"],
        "blocking_items": blockers,
        "streamlit_business_pages_authorized": not blockers,
        "customer_output_allowed": not blockers and week12["customer_output_allowed"],
    }


def main() -> int:
    result = check_week13_gate()
    serialized = json.dumps(result, ensure_ascii=False, indent=2)
    fingerprint = sha256(serialized.encode("utf-8")).hexdigest()[:12]
    report_dir = ROOT / "reports" / "week13_gate" / "runs" / f"run_{fingerprint}"
    report_dir.mkdir(parents=True, exist_ok=True)
    (report_dir / "validation_results.json").write_text(serialized, encoding="utf-8")
    (report_dir / "gate_summary.md").write_text(
        "# Week 13 Admission Gate\n\n"
        f"- Verdict: `{result['verdict']}`\n"
        f"- Week 11: `{result['week11_gate']}`\n"
        f"- Week 12: `{result['week12_gate']}`\n"
        "- Streamlit business pages: blocked until all predecessor Gates pass.\n",
        encoding="utf-8",
    )
    (report_dir / "dependency_status.md").write_text(
        "# Dependency Status\n\n"
        f"- Week11: `{result['week11_gate']}`\n"
        f"- Week12: `{result['week12_gate']}`\n"
        "- Manual-review waiver applies to internal engineering, not to price, evidence, coverage, or customer eligibility.\n",
        encoding="utf-8",
    )
    (report_dir / "ui_readiness.md").write_text(
        "# UI Readiness\n\n"
        "Streamlit business pages remain unimplemented and unauthorized. "
        "The internal market, mapping, evidence, TCO, and decision pipelines are available "
        "through backend services and CLI, but customer output remains blocked.\n",
        encoding="utf-8",
    )
    (report_dir / "unresolved_blockers.md").write_text(
        "# Unresolved Blockers\n\n"
        + "\n".join(f"- `{item}`" for item in result["week12_blockers"])
        + "\n",
        encoding="utf-8",
    )
    (report_dir / "recommended_next_actions.md").write_text(
        "# Recommended Next Actions\n\n"
        "- Resolve non-review Week11 blockers: fresh official prices, complete TCO, joined evidence and decision chain.\n"
        "- Reach the current 85% coverage threshold.\n"
        "- Recheck Week12 and Week13 Gates before creating Streamlit business pages.\n",
        encoding="utf-8",
    )
    result["report_dir"] = str(report_dir)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["verdict"] == "GO" else 1


if __name__ == "__main__":
    raise SystemExit(main())
