from __future__ import annotations

import argparse
import json
from pathlib import Path

from _bootstrap import ROOT as _ROOT  # noqa: F401

from cloud_expert.database.session import SessionLocal
from cloud_expert.decision.pipeline import create_from_config


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    args = parser.parse_args()
    with SessionLocal() as session:
        scenario = create_from_config(session, Path(args.config))
        payload = {
            "scenario_id": scenario.id,
            "scenario_code": scenario.scenario_code,
            "scenario_version": scenario.scenario_version,
            "status": scenario.status,
        }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
