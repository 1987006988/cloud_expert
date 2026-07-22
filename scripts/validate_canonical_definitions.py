import json

import _bootstrap  # noqa: F401

from cloud_expert.normalization.canonical_fields import (
    CANONICAL_FIELD_SEEDS,
    LEGACY_FIELD_MAPPINGS,
    validate_canonical_registry,
)


def main() -> int:
    errors = validate_canonical_registry()
    result = {
        "canonical_fields": len(CANONICAL_FIELD_SEEDS),
        "legacy_mappings": len(LEGACY_FIELD_MAPPINGS),
        "errors": errors,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
