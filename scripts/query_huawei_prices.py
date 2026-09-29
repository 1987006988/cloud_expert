from __future__ import annotations

import argparse
import getpass
import json
import os
from pathlib import Path

from _bootstrap import ROOT
from pydantic import ValidationError

from cloud_expert.pricing.huawei_api import (
    LocalCredentials,
    PricingQuery,
    PricingQueryError,
    credential_status,
    query_prices,
    stage_response,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Read-only Huawei pricing API, local credentials only"
    )
    parser.add_argument("--check-config", action="store_true")
    parser.add_argument(
        "--interactive", action="store_true", help="Hidden local credential prompts"
    )
    parser.add_argument(
        "--request", type=Path, help="Product query JSON; no credentials in this file"
    )
    args = parser.parse_args()
    if args.check_config:
        status = credential_status()
        print(json.dumps({"configured": status, "ready": all(status.values())}))
        return 0 if all(status.values()) else 1
    if args.request is None:
        parser.error("--request is required; use --check-config for a no-network check")
    try:
        query = PricingQuery.model_validate_json(args.request.read_text(encoding="utf-8"))
        token = os.getenv("HUAWEICLOUD_AUTH_TOKEN", "")
        project = os.getenv("HUAWEICLOUD_PROJECT_ID", "")
        if args.interactive:
            token = getpass.getpass("Huawei read-only IAM Token (hidden): ")
            project = getpass.getpass("Huawei project ID (hidden): ")
        credentials = LocalCredentials(token=token, project_id=project)
        raw = query_prices(query, credentials)
        receipt = stage_response(raw, query, ROOT / "test_outputs/huawei_pricing_api")
    except (ValidationError, OSError):
        print(
            json.dumps(
                {
                    "status": "blocked",
                    "reason": "Invalid local credentials or query file; values withheld",
                }
            )
        )
        return 1
    except PricingQueryError as exc:
        print(json.dumps({"status": "blocked", "reason": str(exc)}))
        return 1
    print(json.dumps(receipt, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
