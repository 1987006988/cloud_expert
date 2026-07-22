import csv
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
AUDIT = ROOT / "reports" / "audit" / "week01_06_audit"
TASKS = ROOT / "tasks"


def load_json(name: str, default):
    path = AUDIT / name
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8-sig"))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def table(rows, headers):
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for row in rows:
        lines.append(
            "| " + " | ".join(str(row.get(h, "")).replace("\n", " ") for h in headers) + " |"
        )
    return "\n".join(lines)


def write_report(name: str, text: str) -> None:
    (AUDIT / name).write_text(text.strip() + "\n", encoding="utf-8")


def main() -> None:
    coverage = load_json("coverage.json", {})
    db_counts = load_json("database_counts.json", {})
    chain_summary = load_json("evidence_chain_summary.json", {})
    prompt_hashes = load_json("prompt_attachment_hashes.json", [])
    coverage_pct = round(coverage.get("totals", {}).get("percent_covered", 0), 2)

    origin_rows = []
    origin_csv = AUDIT / "data_origin_summary.csv"
    if origin_csv.exists():
        with origin_csv.open(encoding="utf-8", newline="") as handle:
            origin_rows = list(csv.DictReader(handle))

    week_verdicts = [
        {
            "week": "Week 1",
            "scope": "产品数据模型、迁移、Pydantic、Repository、测试基础",
            "verdict": "PASS_WITH_RISK",
            "reason": "模型、迁移和测试存在并可在 SQLite 验证；但无 git 提交、无 PostgreSQL 实测，默认 DB 已漂移。",
        },
        {
            "week": "Week 2",
            "scope": "官方来源登记、原始快照、采集审计、变更检测",
            "verdict": "PARTIAL",
            "reason": "registry 与 raw snapshot 验证通过；Week2/默认 DB 记录了当前迁移链不存在的旧 revision。",
        },
        {
            "week": "Week 3",
            "scope": "Huawei Cloud ECS/OBS 来源接入和解析",
            "verdict": "PASS_WITH_RISK",
            "reason": "21 来源、21 快照、351 Evidence、228 ProductSpecification；抽样链路通过；9 个 open review。",
        },
        {
            "week": "Week 4",
            "scope": "AWS EC2/S3 来源接入和解析",
            "verdict": "PASS_WITH_RISK",
            "reason": "24 来源、22 快照、5723 Evidence、3873 ProductSpecification；AWS partition 验证通过；1350 open review。",
        },
        {
            "week": "Week 5",
            "scope": "Aliyun ECS/OSS 国内来源接入和解析",
            "verdict": "PASS_WITH_RISK",
            "reason": "26 来源、24 快照、8039 Evidence、6311 ProductSpecification；market/zone/partition 验证通过；82 open review。",
        },
        {
            "week": "Week 6",
            "scope": "统一字段、单位、Scope/Qualifier、标准化和可比性准备",
            "verdict": "PARTIAL",
            "reason": "38 字段、40 规则、10172 normalized rows 可复算；但 projection 丢失 SnapshotRecord/ParsingRun/ServiceTier/Region 等链路。",
        },
    ]

    findings = [
        {
            "id": "F001",
            "severity": "BLOCKER",
            "status": "FAIL",
            "area": "Repository/Git",
            "title": "仓库没有任何 commit，Week1-6 历史不可由 git 复现",
            "impact": "无法独立证明每周交付边界、变更时间线、代码审查点或可回滚版本。",
        },
        {
            "id": "F002",
            "severity": "CRITICAL",
            "status": "FAIL",
            "area": "Default database",
            "title": "默认 cloud_expert_dev.sqlite 使用不存在的 Alembic revision",
            "impact": "README 默认命令和未显式 DATABASE_URL 的验证脚本会落到陈旧数据库并失败。",
        },
        {
            "id": "F003",
            "severity": "CRITICAL",
            "status": "FAIL",
            "area": "Evidence chain",
            "title": "Week6 combined projection 丢失 Evidence -> SnapshotRecord 链路",
            "impact": "NormalizedSpecification 虽有 evidence_id，但 projection 中 snapshot_record=0 且 evidence.snapshot_record_id 为空。",
        },
        {
            "id": "F004",
            "severity": "HIGH",
            "status": "PARTIAL",
            "area": "Cross-week integration",
            "title": "Week6 projection 不是完整的前6周数据底座",
            "impact": "product_family、service_tier、product_sla、region、availability、zone_availability、parsing_run 等均未保留。",
        },
        {
            "id": "F005",
            "severity": "HIGH",
            "status": "PARTIAL",
            "area": "Week6 model completeness",
            "title": "Canonical schema/enums 未覆盖 Week6 Prompt 要求",
            "impact": "缺少多项 qualifier/scope/data type 与 deprecation/precision/null policy 等字段。",
        },
        {
            "id": "F006",
            "severity": "HIGH",
            "status": "PARTIAL",
            "area": "Comparability",
            "title": "ComparabilityAssessment 逻辑过粗",
            "impact": "当前主要按 coverage 和 market_mode 判断，没有充分检查 scope identity、证据快照、review status、单位备注或时效。",
        },
        {
            "id": "F007",
            "severity": "HIGH",
            "status": "PARTIAL",
            "area": "Reports",
            "title": "字段矩阵缺少 Prompt 要求的状态列",
            "impact": "矩阵只能证明 legacy field mapping，不能独立支撑可比性审查。",
        },
        {
            "id": "F008",
            "severity": "HIGH",
            "status": "PARTIAL",
            "area": "Review workflow",
            "title": "人工审核队列未闭合，总计至少 1441 个 open review items",
            "impact": "数据可用于内部工程验证，但不得进入 customer-facing claim、评分或产品映射。",
        },
        {
            "id": "F009",
            "severity": "HIGH",
            "status": "NOT_VERIFIABLE",
            "area": "PostgreSQL",
            "title": "目标数据库 PostgreSQL 未实测",
            "impact": "SQLite 迁移链通过，但 PostgreSQL 约束、枚举和 Decimal 行为仍未被本次审计验证。",
        },
        {
            "id": "F010",
            "severity": "HIGH",
            "status": "FAIL",
            "area": "Coverage",
            "title": f"coverage 总体 {coverage_pct}%，低于 Week6 Prompt 的 85% 门槛",
            "impact": "标准化核心模块覆盖不足，风险集中在 canonical_service、unit_standardization 和 canonical schemas。",
        },
        {
            "id": "F011",
            "severity": "MEDIUM",
            "status": "FAIL",
            "area": "Formatting",
            "title": "ruff format --check 失败，18 个文件需要 reformat",
            "impact": "质量门未全绿，不能声称 Week6 全部质量检查通过。",
        },
        {
            "id": "F012",
            "severity": "MEDIUM",
            "status": "FAIL",
            "area": "Task tracking",
            "title": "tasks/completed/ 缺失",
            "impact": "任务完成记录无法按审计要求从仓库结构核验。",
        },
        {
            "id": "F013",
            "severity": "LOW",
            "status": "PASS_WITH_RISK",
            "area": "Security",
            "title": "未发现真实密钥，但存在本地 docker-compose 测试密码和测试用假 secret 命中",
            "impact": "未发现真实凭据泄漏；docker-compose 密码应仅作为本地测试凭据。",
        },
    ]

    command_rows = [
        {
            "command": "pytest --collect-only -q",
            "result": "PASS",
            "summary": "62 tests collected",
            "artifact": "cmd_pytest_collect_only.txt",
        },
        {
            "command": "ruff format --check .",
            "result": "FAIL",
            "summary": "18 files would be reformatted",
            "artifact": "cmd_ruff_format_check.txt",
        },
        {
            "command": "ruff check .",
            "result": "PASS",
            "summary": "All checks passed",
            "artifact": "cmd_ruff_check.txt",
        },
        {
            "command": "mypy src",
            "result": "PASS",
            "summary": "138 source files, no issues",
            "artifact": "cmd_mypy_src.txt",
        },
        {
            "command": 'pytest -m "not network" -ra',
            "result": "PASS",
            "summary": "62 passed",
            "artifact": "cmd_pytest_not_network_ra.txt",
        },
        {
            "command": "pytest coverage",
            "result": "PASS_WITH_RISK",
            "summary": f"62 passed; coverage {coverage_pct}%",
            "artifact": "cmd_pytest_not_network_coverage.txt",
        },
        {
            "command": "validate_source_registry.py",
            "result": "PASS",
            "summary": "74 valid, 4 disabled, 0 errors",
            "artifact": "cmd_validate_source_registry.txt",
        },
        {
            "command": "validate_raw_snapshots.py",
            "result": "PASS",
            "summary": "90 snapshots checked, 0 errors",
            "artifact": "cmd_validate_raw_snapshots.txt",
        },
        {
            "command": "validate_evidence_links.py default DB",
            "result": "FAIL",
            "summary": "default DB lacks current tables",
            "artifact": "cmd_validate_evidence_links_default_db.txt",
        },
        {
            "command": "alembic current default DB",
            "result": "FAIL",
            "summary": "missing revision 0002_ingestion_runs_and_snapshots",
            "artifact": "cmd_alembic_current_default_db.txt",
        },
        {
            "command": "alembic audit SQLite upgrade/downgrade/reupgrade",
            "result": "PASS",
            "summary": "fresh DB and prior-week copies upgrade to 0006",
            "artifact": "cmd_alembic_audit_empty_upgrade_head.txt",
        },
    ]

    week_table = table(week_verdicts, ["week", "scope", "verdict", "reason"])
    finding_table = table(findings, ["id", "severity", "status", "area", "title", "impact"])
    command_table = table(command_rows, ["command", "result", "summary", "artifact"])

    week6_rows = []
    for row in origin_rows:
        if row.get("database_label") == "week6_combined_projection":
            week6_rows.append(
                {
                    "provider/product": f"{row['provider']}/{row['product']}",
                    "specs": row["product_specification_count"],
                    "normalized": row["normalized_specification_count"],
                    "evidence": row["evidence_count"],
                    "snapshots": row["snapshot_count"],
                    "evidence_without_snapshot": row["evidence_without_snapshot_count"],
                }
            )
    week6_table = table(
        week6_rows,
        [
            "provider/product",
            "specs",
            "normalized",
            "evidence",
            "snapshots",
            "evidence_without_snapshot",
        ],
    )

    write_report(
        "00_executive_summary.md",
        f"""
# Week01-06 Independent Audit Executive Summary

Audit date: {datetime.now(UTC).date().isoformat()} UTC. Scope: Week 1 through Week 6 of `cloud-competitive-expert`.

## Overall Verdict

**Overall: FAIL for reproducibility, PARTIAL for functional completeness, PASS_WITH_RISK for original Week3-5 data authenticity.**

The repository contains substantial implemented code, migrations, parsers, official source registry records, raw snapshots, product data, normalization output, reports, and tests. However, the phase cannot pass an evidence-first release gate because the git repository has no commits, the default database is stale and references a non-existent Alembic revision, and the Week6 combined projection loses the `Evidence -> SnapshotRecord` chain.

## Week Verdicts

{week_table}

## Gate Recommendation

**Week7 gate: NO-GO for product mapping, pricing/TCO, scoring, sales claims, RAG, or frontend.**

Allowed next work should be remediation only: restore version-control provenance, repair default DB reproducibility, rebuild the Week6 projection with full source/snapshot/provenance tables, close or explicitly route human review queues, and strengthen canonical/comparability tests.

## Top Findings

{finding_table}
""",
    )

    write_report(
        "01_repository_and_git_audit.md",
        """
# Repository And Git Audit

## Verdict

**FAIL / BLOCKER.** Git cannot prove the Week1-6 history.

## Evidence

- Branch: `master`.
- Remote: none.
- Tags: none.
- `git log --oneline --decorate --graph -25`: failed because there are no commits.
- `git ls-files`: empty.
- `git status`: all project files are untracked.
- Project file list excluding audit/raw/test output/venv: 345 files.
- Python LOC across `src`, `tests`, `scripts`, and `alembic`: 17582.

## Impact

The working tree may contain real implementation work, but there is no immutable repository provenance. Week-by-week completion claims are therefore not independently reproducible from version control.
""",
    )

    write_report(
        "02_week01_audit.md",
        """
# Week01 Audit

## Verdict

**PASS_WITH_RISK.** The database foundation exists and is covered by tests, but release reproducibility is not acceptable.

## Verified

- SQLAlchemy ORM models exist for providers, products, SKUs, regions, source documents, evidence, specifications, pricing snapshots, mappings, claims, and evaluation scaffolding.
- Alembic `0001_initial_product_data_model` creates the initial schema and supports downgrade.
- Pydantic schemas and repository tests are present.
- `tests/migrations/test_alembic_migration.py` verifies SQLite upgrade, downgrade to base, and re-upgrade.
- `pytest -m "not network" -ra` passed 62 tests.

## Risks

- PostgreSQL was not verified in this audit because Docker daemon was not running.
- No git commit/tag can prove the Week1 baseline.
- The default local DB is no longer aligned with current migrations.
""",
    )

    write_report(
        "03_week02_audit.md",
        """
# Week02 Audit

## Verdict

**PARTIAL.** Source registry and raw snapshots validate, but the historical Week2/default DB uses an obsolete Alembic revision id.

## Verified

- `scripts/validate_source_registry.py` passed: 74 valid sources, 4 disabled, 0 configuration errors.
- `scripts/validate_raw_snapshots.py` passed: 90 snapshots checked, 0 errors.
- Week2 database exists and contains `source_document`, `snapshot_record`, and `ingestion_run` rows.
- Ingestion safety modules and tests cover domain policy, SSRF blocking, redirect blocking, MIME/size handling, sanitized headers, and fixture transport.

## Issues

- `cloud_expert_dev.sqlite` and `week2_e2e_20260721_01.sqlite` record `0002_ingestion_runs_and_snapshots`, but the current migration is named `0002_ingestion_snapshots`.
- Current validators are not backward-compatible with pre-Week5 schemas unless the DB is upgraded first.
""",
    )

    write_report(
        "04_week03_audit.md",
        """
# Week03 Audit

## Verdict

**PASS_WITH_RISK.** Huawei Cloud ECS/OBS source ingestion and parsing are supported by database evidence, but human review is incomplete and Region/Availability remains unstructured.

## Verified Counts

- Source documents: 21.
- Snapshot records: 21.
- Ingestion runs: 21.
- Parsing runs: 21.
- Evidence records: 351.
- Product specifications: 228.
- SKUs: 37.
- Product families: 17.
- Service tiers: 4.
- Product SLA records: 7.
- Review items: 9.

## Evidence Chain

Sampled 10 product specifications across ECS/OBS. All sampled rows linked ProductSpecification -> Evidence -> SourceDocument -> SnapshotRecord.

## Risks

- 9 open low-confidence review items.
- 0 normalized Region rows and 0 Availability rows in Week3 acceptance DB; region material is product-level evidence only.
- Current `validate_evidence_links.py` fails on the unupgraded Week3 DB because it assumes Week5 tables; the upgraded audit copy validates.
""",
    )

    write_report(
        "05_week04_audit.md",
        """
# Week04 Audit

## Verdict

**PASS_WITH_RISK.** AWS EC2/S3 baseline is evidence-backed and partition validation passes, but human review and current-validator compatibility remain risks.

## Verified Counts

- Source documents: 22.
- Snapshot records: 22.
- Ingestion runs: 44.
- Parsing runs: 22.
- Evidence records: 5723.
- Product specifications: 3873.
- EC2 SKUs: 678.
- EC2 product families: 74.
- S3 service tiers: 8.
- Regions: 34.
- Availability rows: 68.
- Review items: 1350.

## Validation

- `validate_source_registry.py --provider aws`: 24 valid, 2 disabled, 0 errors.
- `validate_provider_partitions.py --provider aws --partition aws`: 0 violations.
- Evidence-chain sample passed on original Week4 DB.

## Risks

- 1350 open review items block customer-facing use.
- Availability rows are product-level only and cannot prove SKU/family/storage-class availability.
- Current `validate_evidence_links.py` fails on the unupgraded Week4 DB because it assumes Week5 zone tables; the upgraded audit copy validates.
""",
    )

    write_report(
        "06_week05_audit.md",
        """
# Week05 Audit

## Verdict

**PASS_WITH_RISK.** Aliyun ECS/OSS domestic baseline is evidence-backed and market/zone validation passes, but review remains incomplete.

## Verified Counts

- Source documents: 24.
- Snapshot records: 24.
- Ingestion runs: 24.
- Parsing runs: 24.
- Evidence records: 8039.
- Product specifications: 6311.
- ECS SKUs: 994.
- ECS product families: 208.
- OSS service tiers: 5.
- Regions: 19.
- Availability rows: 34.
- Availability zones: 62.
- Zone availability rows: 62.
- Review items: 82.

## Validation

- `validate_source_registry.py --provider aliyun`: 26 valid, 2 disabled, 0 errors.
- `validate_provider_market_scope.py --provider aliyun`: 0 errors.
- `validate_region_zone_relationships.py --provider aliyun`: 0 errors.
- `validate_provider_partitions.py --provider aliyun`: 0 violations.

## Risks

- 82 open review items.
- Zone/Region availability is product-level only and cannot prove SKU-level or storage-class-level availability.
""",
    )

    write_report(
        "07_week06_audit.md",
        f"""
# Week06 Audit

## Verdict

**PARTIAL.** The canonical normalization layer exists and produces reproducible counts, but it does not satisfy the full Week6 Prompt.

## Verified Counts

- Canonical field definitions: 38.
- Normalization rules: 40.
- Normalization runs: 1.
- Product specifications examined in projection: 10412.
- Normalized specifications: 10172.
- Comparability assessments: 116.
- Normalized review status: 9404 machine_extracted, 768 pending_review.
- Comparability status: 13 comparable, 66 partial, 37 not_comparable.
- Scope mismatch warnings: 90.

## Product Normalization Counts

{week6_table}

## Major Gaps

- Projection DB has 0 `snapshot_record`, 0 `ingestion_run`, 0 `parsing_run`, 0 `product_family`, 0 `service_tier`, 0 `product_sla`, 0 `region`, 0 `availability`, 0 `availability_zone`, and 0 `zone_availability` rows.
- `scripts/build_week6_combined_acceptance.py` copies Evidence with `snapshot_record_id=None`, causing all sampled Week6 projection evidence chains to fail the SnapshotRecord step.
- Field matrices lack required status columns for semantic match, unit match, scope match, qualifier match, evidence status, and comparability status.
- Enums and schema fields are narrower than the Prompt requirement.
- Comparability logic is coverage-based readiness, not a robust comparison blocker system.
""",
    )

    write_report(
        "08_database_audit.md",
        """
# Database Audit

## Verdict

**PARTIAL.** SQLite migration chains are healthy on fresh/prior-week audit databases, but default DB and PostgreSQL verification fail or are not verifiable.

## Passed

- `alembic history`: linear chain from `0001` to `0006`.
- `alembic heads`: single head `0006_week06_canonical_normalization`.
- Fresh audit SQLite DB: `upgrade head`, `downgrade -1`, and `upgrade head` all passed.
- Copies of Week3, Week4, and Week5 acceptance DBs upgraded to head successfully.

## Failed

- Default `cloud_expert_dev.sqlite` cannot run `alembic current`: missing revision `0002_ingestion_runs_and_snapshots`.
- Default `validate_evidence_links.py` fails because the default DB lacks current tables.

## Not Verifiable

- PostgreSQL migration behavior. Docker CLI exists, but Docker daemon was not running during audit.
""",
    )

    write_report(
        "09_test_and_coverage_audit.md",
        f"""
# Test And Coverage Audit

## Verdict

**PARTIAL.** Tests pass, but formatting and coverage gates fail.

## Command Results

{command_table}

## Weak-Test Scan

- `assert True`: no matches.
- `pytest.skip`: no test skip matches; only method names containing `skip` in production summary code.
- `xfail`: no matches.
- `pragma: no cover`: no source/test matches beyond configured coverage settings.
- `coverage: ignore`: no matches.
- `pass`: present mainly in empty Pydantic schema subclasses, not tests.

## Coverage Risk

Overall coverage is **{coverage_pct}%**. Week6-critical files are weaker: `canonical_service.py` 63%, `unit_standardization.py` 40%, and `schemas/canonical.py` 0%.
""",
    )

    write_report(
        "10_data_and_evidence_audit.md",
        """
# Data And Evidence Audit

## Verdict

**PARTIAL.** Original Week3-5 acceptance databases preserve the evidence chain in samples. Week6 projection does not.

## Source Registry And Snapshot Validation

- All registry: 74 valid, 4 disabled, 0 errors.
- Huawei registry: 21 valid, 0 disabled.
- AWS registry: 24 valid, 2 disabled pricing sources.
- Aliyun registry: 26 valid, 2 disabled pricing sources.
- Raw snapshots: 90 checked, 0 hash/path/header errors.

## Evidence Chain Sampling

- Week3 Huawei ECS/OBS: 10/10 sampled rows passed ProductSpecification -> Evidence -> SourceDocument -> SnapshotRecord.
- Week4 AWS EC2/S3: 10/10 sampled rows passed.
- Week5 Aliyun ECS/OSS: 10/10 sampled rows passed.
- Week6 combined projection: 0/30 sampled rows passed the SnapshotRecord step.

## Evidence Link Validators

- Week5 and Week6 current-schema validators pass with 0 missing evidence links.
- Upgraded Week3/4/5 audit copies pass with 0 missing evidence links.
- Default DB fails due stale schema.
""",
    )

    write_report(
        "11_security_and_compliance_audit.md",
        """
# Security And Compliance Audit

## Verdict

**PASS_WITH_RISK.** No real secrets were identified in checked project files, but the scan found expected test/demo credentials and many policy mentions.

## Verified

- No `.env` file is present; only `.env.example` exists.
- `.gitignore` excludes `.env`, `.env.*`, `data/raw`, `test_outputs`, SQLite DBs, and coverage/cache artifacts.
- Sensitive header redaction is implemented and tested.
- Forbidden source classes are documented: console, cookies, AccessKey/API calls, browser-required pages, account-specific data, pricing/TCO, LLM/RAG/frontend.

## Findings

- `docker-compose.yml` contains a local PostgreSQL test password. This is acceptable as sample local config if documented, but should not be reused outside local dev.
- Test files intentionally use fake `secret` values to assert redaction.
- No evidence of real AccessKey, API token, customer data, private quote, or account-specific source ingestion was found.
""",
    )

    write_report(
        "12_cross_week_integration_audit.md",
        """
# Cross-Week Integration Audit

## Verdict

**FAIL for integrated data-store completeness; PARTIAL for derived normalization.**

## What Integrates Correctly

- Week3, Week4, and Week5 acceptance DBs can each upgrade to Week6 schema.
- Week6 normalization can derive canonical rows from copied ProductSpecification/Evidence rows.
- SourceDocument and Evidence counts in Week6 projection match the expected 67 and 14113 counts.

## What Does Not Integrate

- Week6 projection omits raw/source operational tables: SnapshotRecord, IngestionRun, ParsingRun.
- Week6 projection omits product shape and availability tables: ProductFamily, ServiceTier, ProductSLA, CloudPartition, Region, Availability, AvailabilityZone, ZoneAvailability.
- Open review queues are not carried into Week6 projection.
- Object-storage service-tier scope is downgraded to product scope for 90 rows because service-tier identity is not preserved in ProductSpecification.

## Consequence

The Week6 projection is useful as a narrow normalization acceptance artifact, but it is not the claimed full cross-provider competitive product data foundation.
""",
    )

    write_report(
        "13_blockers_and_risks.md",
        f"""
# Blockers And Risks

{finding_table}

## Immediate Blockers

1. No git commits, remote, or tags.
2. Default DB stale and unusable with current migration chain.
3. Week6 projection loses SnapshotRecord provenance.
4. Week6 projection is not a full integrated product dataset.
5. Human review remains open across all real provider data.

## Week7 Risk

Starting Week7 product mapping or sales reasoning now would convert readiness artifacts into unsupported competitive claims. That would violate the evidence-first project policy.
""",
    )

    write_report(
        "14_remediation_plan.md",
        """
# Remediation Plan

## Gate

Do not start Week7 feature work until R001-R008 in `tasks/remediation_backlog.yaml` are complete or explicitly waived by a human owner.

## Priority Order

1. Establish git provenance: create an initial audited baseline commit and tag it as a phase audit snapshot.
2. Repair default DB reproducibility: either rebuild `cloud_expert_dev.sqlite` from current migrations or remove it from default workflows.
3. Rebuild Week6 combined projection so it copies SnapshotRecord, IngestionRun, ParsingRun, ProductFamily, ServiceTier, ProductSLA, CloudPartition, Region, Availability, AvailabilityZone, ZoneAvailability, ReviewItem, and DataQualityIssue where relevant.
4. Preserve `Evidence.snapshot_record_id` during projection and add a validator that checks full SourceDocument/SnapshotRecord/raw manifest chain for normalized rows.
5. Expand Week6 canonical schema/enums and field matrices to match the original Prompt.
6. Strengthen ComparabilityAssessment logic so it records explicit blockers for scope, qualifier, unit, evidence, review status, and market mismatch.
7. Raise coverage above the required threshold and add negative tests around ambiguous units, qualitative network values, service-tier scope, stale evidence, and idempotent new rule versions.
8. Run PostgreSQL migration validation once Docker daemon or another PostgreSQL service is available.
""",
    )

    results = {
        "audit_scope": "week01_06",
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "overall_verdict": {
            "truthfulness": "PARTIAL",
            "completeness": "PARTIAL",
            "reproducibility": "FAIL",
            "week7_gate": "NO_GO",
        },
        "week_verdicts": week_verdicts,
        "findings": findings,
        "commands": command_rows,
        "coverage_percent": coverage_pct,
        "database_counts": db_counts,
        "evidence_chain_summary": chain_summary,
        "prompt_attachment_hashes": prompt_hashes,
    }
    (AUDIT / "audit_results.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    artifacts = []
    for path in sorted(AUDIT.iterdir()):
        if path.is_file() and path.name != "audit_evidence_manifest.json":
            artifacts.append(
                {
                    "path": str(path.relative_to(ROOT)),
                    "bytes": path.stat().st_size,
                    "sha256": sha256(path),
                }
            )
    manifest = {
        "audit_scope": "week01_06",
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "source_prompt_attachments": prompt_hashes,
        "artifacts": artifacts,
    }
    (AUDIT / "audit_evidence_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    backlog = """
items:
  - id: R001_git_provenance_baseline
    severity: BLOCKER
    status: open
    title: Establish version-control provenance for Week1-6 baseline
    rationale: No commits, tags, tracked files, or remote exist; weekly history is not reproducible.
    acceptance_criteria:
      - All intended project files are tracked.
      - Generated/ignored artifacts remain ignored.
      - A baseline commit and audit tag exist.
  - id: R002_default_database_rebuild
    severity: CRITICAL
    status: open
    title: Rebuild or retire stale cloud_expert_dev.sqlite
    rationale: Default DB references non-existent Alembic revision 0002_ingestion_runs_and_snapshots.
    acceptance_criteria:
      - `alembic current` succeeds with default settings or docs require explicit DATABASE_URL.
      - `validate_evidence_links.py` no longer fails on an unintended stale default DB.
  - id: R003_week6_projection_full_provenance
    severity: CRITICAL
    status: open
    title: Preserve SnapshotRecord provenance in Week6 combined projection
    rationale: Current projection sets Evidence.snapshot_record_id to null and has zero snapshot records.
    acceptance_criteria:
      - SnapshotRecord rows are copied or remapped.
      - Evidence rows retain snapshot_record_id and content_hash.
      - NormalizedSpecification samples pass ProductSpecification -> Evidence -> SourceDocument -> SnapshotRecord -> raw manifest.
  - id: R004_week6_projection_complete_dataset
    severity: HIGH
    status: open
    title: Include product shape, SLA, partition, availability, and review tables in combined dataset
    rationale: Current projection omits ProductFamily, ServiceTier, ProductSLA, Region, Availability, ZoneAvailability, ReviewItem, and related rows.
  - id: R005_expand_canonical_schema_to_prompt
    severity: HIGH
    status: open
    title: Expand canonical fields, qualifiers, scopes, data types, and deprecation metadata
    rationale: Week6 schema does not cover all Prompt-required qualifiers/scopes/metadata.
  - id: R006_field_matrix_required_columns
    severity: HIGH
    status: open
    title: Add semantic/unit/scope/qualifier/evidence/comparability status columns to field matrices
    rationale: Current matrices only list mapping rows and provider products.
  - id: R007_strengthen_comparability_assessment
    severity: HIGH
    status: open
    title: Make comparability assessment blocker-aware
    rationale: Current logic mostly counts rows and market-mode mismatch.
  - id: R008_review_queue_policy
    severity: HIGH
    status: open
    title: Route or close open human review queues before customer-facing use
    rationale: At least 1441 open review items remain across Huawei, AWS, and Aliyun data.
  - id: R009_raise_test_coverage
    severity: HIGH
    status: open
    title: Raise coverage and negative test depth for normalization/comparability
    rationale: Overall coverage is below the 85% gate.
  - id: R010_ruff_format_gate
    severity: MEDIUM
    status: open
    title: Run and commit ruff formatting
    rationale: `ruff format --check .` reports 18 files would be reformatted.
  - id: R011_postgresql_migration_validation
    severity: HIGH
    status: open
    title: Run PostgreSQL migration upgrade/downgrade/re-upgrade
    rationale: PostgreSQL is the target DB but Docker daemon was unavailable during audit.
  - id: R012_restore_tasks_completed
    severity: MEDIUM
    status: open
    title: Restore or create task completion ledger according to project governance
    rationale: `tasks/completed/` is required by the audit prompt but missing.
"""
    (TASKS / "remediation_backlog.yaml").write_text(backlog.strip() + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
