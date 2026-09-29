from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

import _bootstrap  # noqa: F401

from cloud_expert.model_review.registry import (
    load_registry,
    probe_codex_cli,
    resolution_payload,
    resolve_model,
)

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "config/model_review/model_registry.yaml"
REPORT = ROOT / "reports/model_review/model_resolution.json"


def main() -> int:
    parser = argparse.ArgumentParser(description="Resolve the highest approved review model.")
    parser.add_argument("--probe", action="store_true", help="Make a read-only model call")
    args = parser.parse_args()
    models, fallback_configured = load_registry(REGISTRY)
    highest = max(
        (model for model in models if model.approved_for_review),
        key=lambda m: m.capability_rank,
        default=None,
    )
    probe = probe_codex_cli(highest.model_id) if args.probe and highest is not None else None
    verified = {highest.model_id} if highest and probe and probe["available"] else set()
    resolution = resolve_model(
        models, verified_available=verified, allow_fallback=fallback_configured
    )
    result = resolution_payload(resolution, probe)
    result["checked_at"] = datetime.now(UTC).isoformat()
    result["registry_path"] = str(REGISTRY)
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if resolution.status == "AVAILABLE" else 1


if __name__ == "__main__":
    raise SystemExit(main())
