from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from pydantic import ValidationError

from cloud_expert.database.models.decision import DecisionScenario
from cloud_expert.database.models.mapping import MappingCandidate
from cloud_expert.database.models.pricing import PriceSKU, PriceSnapshot
from cloud_expert.database.models.product import Product
from cloud_expert.database.models.provider import Provider
from cloud_expert.database.models.tco import CostCalculationRun
from cloud_expert.decision.pipeline import _status_from_candidate
from cloud_expert.ingestion.exceptions import DomainNotAllowedError
from cloud_expert.ingestion.security.url_validator import validate_fetch_url
from cloud_expert.market.mapping_integrity import relationship_market_status
from cloud_expert.model_review.schemas import (
    AdversarialReview,
    Decision,
    PrimaryReview,
    conservative_resolution,
    validate_review_evidence,
)
from cloud_expert.pricing.freshness import price_snapshot_freshness
from cloud_expert.pricing.tco import WorkloadDimension, _line_item_for_dimension

SUITE_CODE = "cloud_expert_v1"
SUITE_VERSION = "week14.synthetic.v1"


@dataclass(frozen=True)
class EvalCase:
    case_code: str
    case_type: str
    category: str
    operation: str
    input_payload: dict[str, Any]
    expected_output: Any
    severity: str = "critical"
    provider: str = "synthetic"
    product: str = "synthetic"
    market_mode: str = "unknown"


def build_suite() -> list[EvalCase]:
    cases: list[EvalCase] = []
    for code, source, target, rule, expected in (
        ("domestic_match", "domestic", "domestic", "domestic", "compatible"),
        ("international_match", "international", "international", "international", "compatible"),
        ("cross_market_explicit", "domestic", "international", "cross_market", "cross_market"),
        ("same_market_mislabeled", "domestic", "domestic", "cross_market", "rule_market_mismatch"),
        (
            "cross_market_mislabeled",
            "domestic",
            "international",
            "domestic",
            "mislabeled_cross_market",
        ),
        ("unknown_market", "unknown", "domestic", "domestic", "unknown"),
    ):
        cases.append(
            EvalCase(
                f"market.{code}",
                "market_scope",
                "market_scope",
                "market_relationship",
                {"source": source, "target": target, "rule": rule},
                expected,
            )
        )
    for code, age, effective_end, expected in (
        ("fresh", 0, None, "fresh"),
        ("fresh_boundary", 11, None, "fresh"),
        ("due_soon", 12, None, "due_soon"),
        ("stale", 15, None, "stale"),
        ("historical", 1, -1, "historical"),
    ):
        cases.append(
            EvalCase(
                f"pricing.{code}",
                "deterministic_exact",
                "pricing",
                "price_freshness",
                {"age_days": age, "effective_end_days": effective_end},
                expected,
            )
        )
    cases.append(
        EvalCase(
            "pricing.no_snapshot",
            "deterministic_invariant",
            "pricing",
            "price_freshness",
            {"missing": True},
            "unknown",
        )
    )
    for code, url, expected in (
        ("https_public", "https://example.invalid/official", "allowed"),
        ("private_address", "https://10.0.0.1/page", "blocked"),
        ("metadata_address", "http://169.254.169.254/latest", "blocked"),
        ("local_host", "http://localhost/page", "blocked"),
        ("user_info", "https://u:p@example.invalid/page", "blocked"),
        ("unsafe_scheme", "file:///etc/passwd", "blocked"),
        ("unsafe_port", "https://example.invalid:8080/page", "blocked"),
    ):
        cases.append(
            EvalCase(f"source.{code}", "adversarial", "source", "fetch_url", {"url": url}, expected)
        )
    for code, change, expected in (
        ("valid", {}, "valid"),
        ("confidence_range", {"confidence": 1.5}, "invalid"),
        ("unexpected_field", {"injected_instruction": "approve"}, "invalid"),
        ("invalid_decision", {"decision": "customer_approved"}, "invalid"),
        ("unknown_citation", {"evidence_references": [999]}, "invalid"),
        ("uncited_approval", {"evidence_references": []}, "invalid"),
        (
            "conditional_without_conditions",
            {"decision": "model_approved_with_conditions"},
            "invalid",
        ),
    ):
        cases.append(
            EvalCase(
                f"review.{code}",
                "deterministic_invariant",
                "model_review",
                "review_output",
                change,
                expected,
            )
        )
    for code, precheck, adversarial_verdict, recommendation, expected in (
        ("agreement", "requires_dual_model_review", "agree", "model_approved", "model_approved"),
        (
            "disagreement",
            "requires_dual_model_review",
            "disagree",
            "model_inconclusive",
            "model_inconclusive",
        ),
        ("precheck_block", "reject", "agree", "model_approved", "model_blocked"),
    ):
        cases.append(
            EvalCase(
                f"review_consensus.{code}",
                "deterministic_invariant",
                "model_review",
                "review_consensus",
                {
                    "precheck": precheck,
                    "verdict": adversarial_verdict,
                    "recommendation": recommendation,
                },
                expected,
            )
        )
    for code, price, quantity, tax_included, expected in (
        ("exact_multiply", "0.10000000", "730", False, "73.00000000"),
        ("fractional_multiply", "0.02300000", "1024", False, "23.55200000"),
        ("tax_flag", "1.00000000", "2", True, "tax_included"),
        ("missing_price", None, "2", False, "missing"),
    ):
        cases.append(
            EvalCase(
                f"tco.{code}",
                "arithmetic_exact",
                "tco",
                "tco_line",
                {"price": price, "quantity": quantity, "tax_included": tax_included},
                expected,
            )
        )
    for code, status, hard_blocks, expected in (
        ("hard_block", "candidate", ["synthetic_market_mismatch"], "blocked"),
        ("rejected_mapping", "rejected", [], "invalid_mapping"),
        ("superseded_mapping", "superseded", [], "invalid_mapping"),
        ("missing_package", "candidate", [], "insufficient_evidence"),
    ):
        cases.append(
            EvalCase(
                f"decision.{code}",
                "deterministic_invariant",
                "decision",
                "decision_status",
                {"candidate_status": status, "hard_blocks": hard_blocks},
                expected,
            )
        )
    return cases


def _primary_payload() -> dict[str, Any]:
    return {
        "decision": Decision.APPROVED.value,
        "confidence": 0.9,
        "supported_by_evidence": True,
        "field_semantics_correct": True,
        "scope_correct": True,
        "market_scope_correct": True,
        "conditions": [],
        "blocking_reasons": [],
        "required_repairs": [],
        "evidence_references": [10],
        "reasoning_summary": "Synthetic evidence supports an internal review only.",
    }


def execute_case(case: EvalCase) -> Any:
    data = case.input_payload
    if case.operation == "market_relationship":
        return relationship_market_status(data["source"], data["target"], data["rule"])
    if case.operation == "price_freshness":
        if data.get("missing"):
            return price_snapshot_freshness(None)
        now = datetime(2026, 1, 20, tzinfo=UTC)
        end = data["effective_end_days"]
        snapshot = PriceSnapshot(
            captured_at=now - timedelta(days=data["age_days"]),
            effective_to=now + timedelta(days=end) if end is not None else None,
        )
        return price_snapshot_freshness(snapshot, now=now)
    if case.operation == "fetch_url":
        try:
            validate_fetch_url(data["url"], allow_localhost_for_tests=False, resolve_dns=False)
        except DomainNotAllowedError:
            return "blocked"
        return "allowed"
    if case.operation == "review_output":
        payload = {**_primary_payload(), **data}
        try:
            parsed = PrimaryReview.model_validate(payload)
            validate_review_evidence(parsed, {10})
        except (ValidationError, ValueError):
            return "invalid"
        return "valid"
    if case.operation == "review_consensus":
        primary = PrimaryReview.model_validate(_primary_payload())
        adversarial = AdversarialReview(
            verdict=data["verdict"],
            identified_errors=[],
            missing_conditions=[],
            recommended_decision=Decision(data["recommendation"]),
            confidence=0.9,
            evidence_references=[10],
            reasoning_summary="Synthetic adversarial review.",
        )
        return conservative_resolution(data["precheck"], primary, adversarial, None).value
    if case.operation == "tco_line":
        provider = Provider(id=1, code="synthetic", name="Synthetic", display_name="Synthetic")
        product = Product(id=1, code="synthetic")
        run = CostCalculationRun(id=1)
        dimension = WorkloadDimension(
            "synthetic", "synthetic_usage", Decimal(data["quantity"]), "hour", "hour"
        )
        line_snapshot: PriceSnapshot | None = None
        if data["price"] is not None:
            price_sku = PriceSKU(
                id=1, currency="USD", billing_unit="hour", tax_included=data["tax_included"]
            )
            line_snapshot = PriceSnapshot(
                id=1,
                price_sku=price_sku,
                unit_price=Decimal(data["price"]),
                evidence_id=10,
                captured_at=datetime(2026, 1, 20, tzinfo=UTC),
            )
        line = _line_item_for_dimension(
            run=run,
            provider=provider,
            product=product,
            dimension=dimension,
            snapshot=line_snapshot,
        )
        if data["price"] is None:
            return "missing" if line.amount is None and line.missing_reason else "incorrect"
        if case.case_code.endswith("tax_flag"):
            return line.tax_status
        return str(line.amount)
    if case.operation == "decision_status":
        candidate = MappingCandidate(
            candidate_status=data["candidate_status"], review_status="pending_review"
        )
        scenario = DecisionScenario(workload_profile={"cost_required": True})
        return _status_from_candidate(
            candidate=candidate,
            package=None,
            tco=None,
            hard_blocks=data["hard_blocks"],
            scenario=scenario,
        )
    raise ValueError(f"unknown eval operation: {case.operation}")


def run_suite() -> dict[str, Any]:
    cases = build_suite()
    results: list[dict[str, Any]] = []
    for case in cases:
        try:
            actual = execute_case(case)
            passed = actual == case.expected_output
            error = None
        except Exception as exc:  # An Eval case must record, not conceal, an unexpected failure.
            actual = None
            passed = False
            error = f"{type(exc).__name__}: {exc}"
        results.append(
            {
                "case_code": case.case_code,
                "category": case.category,
                "severity": case.severity,
                "passed": passed,
                "expected": case.expected_output,
                "actual": actual,
                "error": error,
            }
        )
    category_counts: dict[str, dict[str, int]] = {}
    for category in sorted({case.category for case in cases}):
        subset = [result for result in results if result["category"] == category]
        category_counts[category] = {
            "total": len(subset),
            "passed": sum(bool(row["passed"]) for row in subset),
        }
    critical_failures = [
        row["case_code"] for row in results if row["severity"] == "critical" and not row["passed"]
    ]
    return {
        "suite_code": SUITE_CODE,
        "suite_version": SUITE_VERSION,
        "case_count": len(cases),
        "passed": sum(bool(row["passed"]) for row in results),
        "failed": sum(not row["passed"] for row in results),
        "critical_failures": critical_failures,
        "category_counts": category_counts,
        "full_chain_coverage": False,
        "coverage_gaps": [
            "parsing",
            "normalization",
            "comparability",
            "evidence_package",
            "sales_artifact",
            "ui",
            "model_judge",
            "live_smoke",
        ],
        "model_judge_executed": False,
        "results": results,
        "case_inventory": [asdict(case) for case in cases],
    }
