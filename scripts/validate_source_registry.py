import argparse
import json
from pathlib import Path

import _bootstrap  # noqa: F401

from cloud_expert.ingestion.registry.validator import summarize_validation, validate_registry


def _matches_filters(
    source_id: str,
    file_path: str,
    provider: str | None,
    product: str | None,
    market_mode: str | None,
) -> bool:
    haystack = f"{source_id} {file_path}".lower()
    if provider and provider.lower() not in haystack:
        return False
    if product and product.lower() not in haystack:
        return False
    return not (market_mode and market_mode.lower() not in haystack)


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate source registry YAML files.")
    parser.add_argument("--registry-dir", type=Path, default=None)
    parser.add_argument("--provider", default=None)
    parser.add_argument("--product", default=None)
    parser.add_argument("--market-mode", choices=["domestic", "international"], default=None)
    args = parser.parse_args()

    results = validate_registry(args.registry_dir)
    if args.provider or args.product or args.market_mode:
        results = [
            result
            for result in results
            if _matches_filters(
                result.source_id or "",
                result.file_path or "",
                args.provider,
                args.product,
                args.market_mode,
            )
        ]
    summary = summarize_validation(results)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    for result in results:
        if not result.valid:
            print(json.dumps(result.model_dump(), ensure_ascii=False, indent=2))
    return 1 if summary["configuration_errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
