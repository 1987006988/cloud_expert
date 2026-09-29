from pathlib import Path

import pytest
from sqlalchemy import select

from cloud_expert.database.models.decision import CandidateDecisionResult
from cloud_expert.database.models.evidence_package import EvidencePackage
from cloud_expert.decision import reporting
from cloud_expert.decision.pipeline import (
    create_from_config,
    result_rows,
    run_decision_engine,
    write_review_sample,
)
from cloud_expert.decision.validation import validate_policy_directory, validate_scenario_directory
from cloud_expert.evidence_packages.builder import build_evidence_packages
from cloud_expert.evidence_packages.render import export_package
from cloud_expert.evidence_packages.validation import (
    customer_output_eligibility_summary,
    evidence_package_counts,
    validate_evidence_package_idempotency,
    validate_evidence_references,
)
from cloud_expert.ingestion.fetcher import SourceFetcher
from cloud_expert.ingestion.storage.snapshot_store import SnapshotStore
from cloud_expert.mapping.pipeline import generate_all_mapping_candidates
from cloud_expert.mapping.reports import export_review_sample, write_mapping_reports
from cloud_expert.mapping.validation import (
    mapping_counts,
    validate_mapping_idempotency,
    validate_mapping_rules,
)
from cloud_expert.normalization.canonical_service import (
    assess_comparability,
    normalize_specifications,
)
from cloud_expert.parsing.pipeline import parse_source_entry
from cloud_expert.pricing.tco import generate_internal_tco
from tests.unit.test_aliyun_parsing_pipeline import _aliyun_fixture_entry
from tests.unit.test_aws_parsing_pipeline import _aws_fixture_entry
from tests.unit.test_huawei_parsing_pipeline import _fixture_entry


@pytest.fixture
def synthetic_chain(session, tmp_path):
    store = SnapshotStore(tmp_path / "raw")
    factory_prefixes = [
        (_fixture_entry, "huawei", "huawei_cloud"),
        (_aws_fixture_entry, "aws", "aws"),
        (_aliyun_fixture_entry, "aliyun", "aliyun"),
    ]
    for factory, file_prefix, source_prefix in factory_prefixes:
        products = (
            ("ec2", "s3")
            if source_prefix == "aws"
            else ("ecs", "obs" if source_prefix == "huawei_cloud" else "oss")
        )
        for product in products:
            kind = "specs" if product in {"ec2", "ecs"} else "storage"
            entry = factory(
                Path(f"tests/fixtures/{file_prefix}_{product}_{kind}_fixture.html"),
                source_id=f"{source_prefix}_{product}_synthetic_{kind}",
                product_code=product,
            )
            SourceFetcher(snapshot_store=store).fetch(entry, session=session)
            parsed = parse_source_entry(session, entry, store)
            assert parsed.error_message is None
            assert parsed.records_found > 0
    normalized = normalize_specifications(session, run_key="synthetic_full_chain")
    assert normalized.records_created > 0
    assess_comparability(session, run_key="synthetic_full_chain")
    mappings = generate_all_mapping_candidates(session)
    assert mappings.total_candidates > 0
    return session


def test_mapping_and_evidence_builds_are_idempotent_and_fail_closed(synthetic_chain, tmp_path):
    session = synthetic_chain
    before = mapping_counts(session)
    generate_all_mapping_candidates(session)
    assert validate_mapping_idempotency(before, mapping_counts(session))["valid"]
    assert validate_mapping_rules(session)["valid"]
    summary = write_mapping_reports(session, tmp_path / "mapping")
    assert summary
    assert export_review_sample(session, tmp_path / "mapping.csv") > 0
    first = build_evidence_packages(session)
    assert first.packages > 0
    assert first.customer_eligible == 0
    counts = evidence_package_counts(session)
    build_evidence_packages(session)
    assert validate_evidence_package_idempotency(counts, evidence_package_counts(session))["valid"]
    assert validate_evidence_references(session)["valid"]
    assert customer_output_eligibility_summary(session)["valid"]
    package = session.scalar(select(EvidencePackage))
    assert export_package(session, package.package_code, tmp_path / "package.json", "json")
    assert export_package(session, package.package_code, tmp_path / "package.md", "markdown")
    assert not export_package(session, "does-not-exist", tmp_path / "missing.json", "json")


def test_decisions_do_not_promote_missing_prices_or_unreviewed_facts(
    synthetic_chain, tmp_path, monkeypatch
):
    session = synthetic_chain
    build_evidence_packages(session)
    tco = generate_internal_tco(session)
    assert tco["warnings"] > 0
    assert generate_internal_tco(session)["created"] is False
    assert validate_policy_directory()["valid"]
    assert validate_scenario_directory()["valid"]
    monkeypatch.setattr(reporting, "REPORT_DIR", tmp_path / "decisions")
    for config in Path("config/decision/scenarios").glob("*.yaml"):
        scenario = create_from_config(session, config)
        first = run_decision_engine(session, scenario.scenario_code)
        assert first.candidate_count > 0
        second = run_decision_engine(session, scenario.scenario_code)
        assert second.created is False
        assert second.run_code == first.run_code
        rows = result_rows(session, first.run_code)
        assert rows
        payload = reporting.write_decision_reports(session, first.run_code)
        assert payload
        reporting.export_markdown_report(
            session, first.run_code, tmp_path / f"{scenario.scenario_code}.md"
        )
        write_review_sample(session, first.run_code, tmp_path / f"{scenario.scenario_code}.csv")
    results = list(session.scalars(select(CandidateDecisionResult)))
    assert results
    assert all(not result.customer_eligible for result in results)
    assert all(result.output_level != "customer_eligible_candidate" for result in results)
    assert all(result.review_status != "human_reviewed" for result in results)
