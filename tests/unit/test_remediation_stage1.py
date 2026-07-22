import sys
from datetime import UTC, datetime
from decimal import Decimal
from hashlib import sha256
from pathlib import Path
from uuid import uuid4

from sqlalchemy.orm import Session

from cloud_expert.config.settings import PROJECT_ROOT, resolve_database_url
from cloud_expert.database.enums import (
    CanonicalDomain,
    ChangeStatus,
    DataType,
    EvidenceType,
    NormalizationRuleType,
    NormalizationRunStatus,
    ReviewStatus,
    SpecificationScopeType,
    ValueQualifier,
)
from cloud_expert.database.models.canonical import (
    CanonicalFieldDefinition,
    NormalizationRule,
    NormalizationRun,
    NormalizedSpecification,
)
from cloud_expert.database.models.snapshot import SnapshotRecord
from cloud_expert.database.models.source import Evidence
from tests.fixtures.synthetic_data import load_synthetic_fixture

SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))


def test_default_sqlite_url_resolves_to_project_root() -> None:
    url = resolve_database_url("sqlite:///./cloud_expert_dev.sqlite")

    assert url == f"sqlite:///{(PROJECT_ROOT / 'cloud_expert_dev.sqlite').as_posix()}"


def test_relink_normalized_evidence_repairs_existing_chain(session: Session) -> None:
    from scripts.relink_normalized_evidence import relink_normalized_evidence

    fixture = load_synthetic_fixture(session)
    source_document = fixture["source_document"]
    evidence = fixture["evidence"]
    specification = fixture["specification"]
    wrong_evidence = Evidence(
        source_document_id=source_document.id,
        locator="html:#wrong",
        excerpt="Wrong evidence used only to test relinking.",
        evidence_type=EvidenceType.HTML_SECTION.value,
        confidence=0.5,
        review_status=ReviewStatus.PENDING_REVIEW.value,
    )
    snapshot = SnapshotRecord(
        source_document_id=source_document.id,
        source_id="synthetic-source",
        content_hash=source_document.content_hash,
        storage_path="synthetic/raw.bin",
        manifest_path="synthetic/manifest.json",
        content_type="text/html",
        content_length_bytes=1,
        captured_at=datetime.now(UTC),
        change_status=ChangeStatus.FIRST_SEEN.value,
        is_current=True,
    )
    field = CanonicalFieldDefinition(
        code="synthetic.canonical.count",
        name="Synthetic canonical count",
        domain=CanonicalDomain.COMPUTE.value,
        data_type=DataType.NUMERIC.value,
        canonical_unit="count",
        unit_dimension="count",
        default_qualifier=ValueQualifier.EXACT.value,
        default_scope_type=SpecificationScopeType.SKU.value,
        is_comparable=True,
    )
    rule = NormalizationRule(
        code="synthetic.rule",
        version="v1",
        rule_type=NormalizationRuleType.FIELD_MAPPING.value,
        canonical_field=field,
        value_qualifier=ValueQualifier.EXACT.value,
        scope_type=SpecificationScopeType.SKU.value,
        is_active=True,
    )
    run = NormalizationRun(
        run_key="synthetic-remediation-run",
        status=NormalizationRunStatus.SUCCEEDED.value,
        started_at=datetime.now(UTC),
        records_examined=1,
        records_created=1,
        records_updated=0,
        records_skipped=0,
        review_items_created=0,
    )
    session.add_all([wrong_evidence, snapshot, field, rule, run])
    session.flush()
    normalized = NormalizedSpecification(
        product_specification_id=specification.id,
        product_id=specification.product_id,
        sku_id=specification.sku_id,
        canonical_field_id=field.id,
        normalization_rule_id=rule.id,
        normalization_run_id=run.id,
        evidence_id=wrong_evidence.id,
        scope_type=SpecificationScopeType.SKU.value,
        scope_identity="synthetic-sku-a",
        value_qualifier=ValueQualifier.EXACT.value,
        numeric_value=Decimal("2"),
        raw_value="synthetic 2",
        raw_unit="count",
        canonical_value="2",
        canonical_unit="count",
        quality_score=Decimal("1.0000"),
        review_status=ReviewStatus.MACHINE_EXTRACTED.value,
        source_value_hash="synthetic-source-value-hash",
    )
    session.add(normalized)
    session.flush()

    result = relink_normalized_evidence(session, dry_run=False)

    assert result["unresolved_total"] == 0
    assert evidence.snapshot_record_id == snapshot.id
    assert normalized.evidence_id == specification.evidence_id


def test_week06_chain_validator_checks_manifest_and_raw_hash(
    session: Session,
    monkeypatch,
) -> None:
    from scripts import validate_week06_projection

    fixture = load_synthetic_fixture(session)
    source_document = fixture["source_document"]
    evidence = fixture["evidence"]
    specification = fixture["specification"]
    raw_bytes = b"synthetic official page body"
    digest = sha256(raw_bytes).hexdigest()
    raw_root = PROJECT_ROOT / ".tmp" / "remediation_stage1_unit" / uuid4().hex
    raw_path = raw_root / "synthetic" / "raw.bin"
    manifest_path = raw_root / "synthetic" / "manifest.json"
    raw_path.parent.mkdir(parents=True)
    raw_path.write_bytes(raw_bytes)
    manifest_path.write_text(f'{{"content_sha256":"{digest}"}}', encoding="utf-8")
    snapshot = SnapshotRecord(
        source_document_id=source_document.id,
        source_id="synthetic-source",
        content_hash=digest,
        storage_path="synthetic/raw.bin",
        manifest_path="synthetic/manifest.json",
        content_type="text/html",
        content_length_bytes=len(raw_bytes),
        captured_at=datetime.now(UTC),
        change_status=ChangeStatus.FIRST_SEEN.value,
        is_current=True,
    )
    field = CanonicalFieldDefinition(
        code="synthetic.canonical.count",
        name="Synthetic canonical count",
        domain=CanonicalDomain.COMPUTE.value,
        data_type=DataType.NUMERIC.value,
        canonical_unit="count",
        unit_dimension="count",
        default_qualifier=ValueQualifier.EXACT.value,
        default_scope_type=SpecificationScopeType.SKU.value,
        is_comparable=True,
    )
    rule = NormalizationRule(
        code="synthetic.rule",
        version="v1",
        rule_type=NormalizationRuleType.FIELD_MAPPING.value,
        canonical_field=field,
        value_qualifier=ValueQualifier.EXACT.value,
        scope_type=SpecificationScopeType.SKU.value,
        is_active=True,
    )
    run = NormalizationRun(
        run_key="synthetic-validation-run",
        status=NormalizationRunStatus.SUCCEEDED.value,
        started_at=datetime.now(UTC),
        records_examined=1,
        records_created=1,
        records_updated=0,
        records_skipped=0,
        review_items_created=0,
    )
    session.add_all([snapshot, field, rule, run])
    session.flush()
    evidence.snapshot_record_id = snapshot.id
    evidence.content_hash = digest
    normalized = NormalizedSpecification(
        product_specification_id=specification.id,
        product_id=specification.product_id,
        sku_id=specification.sku_id,
        canonical_field_id=field.id,
        normalization_rule_id=rule.id,
        normalization_run_id=run.id,
        evidence_id=evidence.id,
        scope_type=SpecificationScopeType.SKU.value,
        scope_identity="synthetic-sku-a",
        value_qualifier=ValueQualifier.EXACT.value,
        numeric_value=Decimal("2"),
        raw_value="synthetic 2",
        raw_unit="count",
        canonical_value="2",
        canonical_unit="count",
        quality_score=Decimal("1.0000"),
        review_status=ReviewStatus.MACHINE_EXTRACTED.value,
        source_value_hash="synthetic-source-value-hash",
    )
    session.add(normalized)
    session.flush()
    monkeypatch.setattr(validate_week06_projection, "RAW_ROOT", raw_root)
    validate_week06_projection._HASH_CACHE.clear()

    assert validate_week06_projection._validate_chain(session, normalized.id) is None
