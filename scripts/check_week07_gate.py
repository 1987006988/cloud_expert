from __future__ import annotations

import json
from typing import Any

import yaml
from _bootstrap import ROOT


def check_week07_gate() -> dict[str, Any]:
    backlog = yaml.safe_load(
        (ROOT / "tasks" / "remediation_backlog.yaml").read_text(encoding="utf-8")
    )
    unresolved: list[dict[str, str]] = []
    for item in backlog.get("items", []):
        status = str(item.get("status", "unknown"))
        if status not in {"complete", "waived_by_owner"}:
            unresolved.append({"id": str(item.get("id")), "status": status})
    waiver = ROOT / "reports" / "remediation" / "r008_waiver" / "waiver_results.json"
    result = {
        "gate": "WEEK7_GATE",
        "verdict": "GO" if not unresolved and waiver.exists() else "NO-GO",
        "unresolved": unresolved,
        "r008_waiver_present": waiver.exists(),
        "allowed_statuses": ["complete", "waived_by_owner"],
        "notes": (
            "R008 waiver allows internal engineering only; pending review facts are not customer eligible."
        ),
    }
    return result


def main() -> int:
    result = check_week07_gate()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["verdict"] == "GO" else 1


if __name__ == "__main__":
    raise SystemExit(main())
