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
        "would_seed_canonical_fields": len(CANONICAL_FIELD_SEEDS),
        "would_seed_normalization_rules": len(LEGACY_FIELD_MAPPINGS),
        "requires_alembic_revision": "0006_week06_canonical_normalization",
        "errors": errors,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
