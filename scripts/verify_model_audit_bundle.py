"""Read-only audit-bundle verification; no Gate, database, or report writes."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import _bootstrap  # noqa: F401

from cloud_expert.model_review.reproducibility import (
    DEFAULT_POLICY,
    audit_bundle_schema,
    validate_audit_bundle,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("audit_dir", type=Path, nargs="?")
    parser.add_argument(
        "--schema", action="store_true", help="Print schemas and builder steps only"
    )
    parser.add_argument("--manifest", default="audit_bundle.json", help="Audit-relative POSIX path")
    parser.add_argument("--policy", type=Path, default=DEFAULT_POLICY)
    parser.add_argument("--expected-release-id")
    parser.add_argument("--expected-artifact-fingerprint")
    parser.add_argument("--expected-subject-hash")
    parser.add_argument("--expected-manifest-sha256")
    parser.add_argument(
        "--synthetic", action="store_true", help="Fixture check; never authorizes an RC"
    )
    args = parser.parse_args(argv)
    if args.schema:
        print(json.dumps(audit_bundle_schema(), indent=2))
        return 0
    if not all(
        (
            args.audit_dir,
            args.expected_release_id,
            args.expected_artifact_fingerprint,
            args.expected_subject_hash,
            args.expected_manifest_sha256,
        )
    ):
        parser.error(
            "audit_dir and all four independently supplied --expected-* values are required"
        )
    result = validate_audit_bundle(
        args.audit_dir,
        manifest_path=args.manifest,
        policy_path=args.policy,
        expected_release_id=args.expected_release_id,
        expected_artifact_fingerprint=args.expected_artifact_fingerprint,
        expected_subject_hash=args.expected_subject_hash,
        expected_manifest_sha256=args.expected_manifest_sha256,
        allow_synthetic=args.synthetic,
    )
    print(json.dumps(result, indent=2))
    # A synthetic structural success must not become a release pass via exit status.
    return 0 if result["policy_satisfied"] else (2 if result["valid"] else 1)


if __name__ == "__main__":
    raise SystemExit(main())
