from collections import Counter
from pathlib import Path

from pydantic import ValidationError

from cloud_expert.ingestion.registry.loader import iter_registry_files, load_yaml_file
from cloud_expert.ingestion.registry.schemas import SourceRegistryEntry, SourceValidationResult


def validate_registry(registry_dir: Path | None = None) -> list[SourceValidationResult]:
    results: list[SourceValidationResult] = []
    parsed_entries: list[SourceRegistryEntry] = []
    source_ids: list[str] = []

    for path in iter_registry_files(registry_dir):
        source_id: str | None = None
        try:
            data = load_yaml_file(path)
            source_id = data.get("source_id") if isinstance(data.get("source_id"), str) else None
            entry = SourceRegistryEntry.model_validate(data)
            parsed_entries.append(entry)
            source_ids.append(entry.source_id)
            results.append(
                SourceValidationResult(
                    source_id=entry.source_id,
                    file_path=str(path),
                    valid=True,
                    enabled=entry.enabled,
                    warnings=[] if entry.enabled else ["source disabled"],
                )
            )
        except (ValidationError, ValueError) as exc:
            results.append(
                SourceValidationResult(
                    source_id=source_id,
                    file_path=str(path),
                    valid=False,
                    errors=[str(exc)],
                )
            )

    duplicate_ids = {source_id for source_id, count in Counter(source_ids).items() if count > 1}
    if duplicate_ids:
        for result in results:
            if result.source_id in duplicate_ids:
                result.valid = False
                result.errors.append(f"duplicate source_id: {result.source_id}")
    return results


def summarize_validation(results: list[SourceValidationResult]) -> dict[str, int]:
    return {
        "total_sources": len(results),
        "valid_sources": sum(result.valid for result in results),
        "disabled_sources": sum(result.enabled is False for result in results),
        "configuration_errors": sum(not result.valid for result in results),
        "duplicate_source_ids": len(
            {
                result.source_id
                for result in results
                if any("duplicate source_id" in error for error in result.errors)
            }
        ),
    }
