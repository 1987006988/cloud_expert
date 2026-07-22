import argparse
import json
from pathlib import Path

import _bootstrap  # noqa: F401
from sqlalchemy.orm import Session

from cloud_expert.database.session import SessionLocal
from cloud_expert.ingestion.fetcher import SourceFetcher
from cloud_expert.ingestion.registry.loader import load_registry_entries
from cloud_expert.ingestion.registry.schemas import SourceRegistryEntry


def _filter_entries(args: argparse.Namespace) -> list[SourceRegistryEntry]:
    entries = load_registry_entries(args.registry_dir)
    if args.source_id:
        entries = [entry for entry in entries if entry.source_id == args.source_id]
    if args.provider:
        entries = [entry for entry in entries if entry.provider_code == args.provider]
    if args.product:
        entries = [entry for entry in entries if entry.product_code == args.product]
    if args.market_mode:
        entries = [entry for entry in entries if str(entry.market_mode) == args.market_mode]
    if args.enabled_only:
        entries = [entry for entry in entries if entry.enabled]
    return entries


def _run_entries(
    entries: list[SourceRegistryEntry], args: argparse.Namespace, session: Session
) -> int:
    fetcher = SourceFetcher()
    exit_code = 0
    for entry in entries:
        if not entry.enabled and args.enabled_only:
            continue
        outcome = fetcher.fetch(
            entry,
            session=session,
            dry_run=args.dry_run,
            force=args.force,
        )
        print(json.dumps(outcome.__dict__, ensure_ascii=False, indent=2, default=str))
        if outcome.status in {"failed", "blocked"}:
            exit_code = 1
    return exit_code


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch registered source snapshots.")
    parser.add_argument("--registry-dir", type=Path, default=None)
    parser.add_argument("--source-id")
    parser.add_argument("--provider")
    parser.add_argument("--product")
    parser.add_argument("--market-mode", choices=["domestic", "international"])
    parser.add_argument("--enabled-only", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--max-concurrency", type=int, default=1)
    args = parser.parse_args()

    if args.max_concurrency > 2:
        print("max_concurrency is capped at 2 for Week 2 safety")
        return 1
    entries = _filter_entries(args)
    if not entries:
        print("No matching source registry entries.")
        return 1
    with SessionLocal() as session:
        return _run_entries(entries, args, session)


if __name__ == "__main__":
    raise SystemExit(main())
