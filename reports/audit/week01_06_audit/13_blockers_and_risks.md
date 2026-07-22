# Blockers And Risks

| id | severity | status | area | title | impact |
| --- | --- | --- | --- | --- | --- |
| F001 | BLOCKER | FAIL | Repository/Git | 仓库没有任何 commit，Week1-6 历史不可由 git 复现 | 无法独立证明每周交付边界、变更时间线、代码审查点或可回滚版本。 |
| F002 | CRITICAL | FAIL | Default database | 默认 cloud_expert_dev.sqlite 使用不存在的 Alembic revision | README 默认命令和未显式 DATABASE_URL 的验证脚本会落到陈旧数据库并失败。 |
| F003 | CRITICAL | FAIL | Evidence chain | Week6 combined projection 丢失 Evidence -> SnapshotRecord 链路 | NormalizedSpecification 虽有 evidence_id，但 projection 中 snapshot_record=0 且 evidence.snapshot_record_id 为空。 |
| F004 | HIGH | PARTIAL | Cross-week integration | Week6 projection 不是完整的前6周数据底座 | product_family、service_tier、product_sla、region、availability、zone_availability、parsing_run 等均未保留。 |
| F005 | HIGH | PARTIAL | Week6 model completeness | Canonical schema/enums 未覆盖 Week6 Prompt 要求 | 缺少多项 qualifier/scope/data type 与 deprecation/precision/null policy 等字段。 |
| F006 | HIGH | PARTIAL | Comparability | ComparabilityAssessment 逻辑过粗 | 当前主要按 coverage 和 market_mode 判断，没有充分检查 scope identity、证据快照、review status、单位备注或时效。 |
| F007 | HIGH | PARTIAL | Reports | 字段矩阵缺少 Prompt 要求的状态列 | 矩阵只能证明 legacy field mapping，不能独立支撑可比性审查。 |
| F008 | HIGH | PARTIAL | Review workflow | 人工审核队列未闭合，总计至少 1441 个 open review items | 数据可用于内部工程验证，但不得进入 customer-facing claim、评分或产品映射。 |
| F009 | HIGH | NOT_VERIFIABLE | PostgreSQL | 目标数据库 PostgreSQL 未实测 | SQLite 迁移链通过，但 PostgreSQL 约束、枚举和 Decimal 行为仍未被本次审计验证。 |
| F010 | HIGH | FAIL | Coverage | coverage 总体 78.6%，低于 Week6 Prompt 的 85% 门槛 | 标准化核心模块覆盖不足，风险集中在 canonical_service、unit_standardization 和 canonical schemas。 |
| F011 | MEDIUM | FAIL | Formatting | ruff format --check 失败，18 个文件需要 reformat | 质量门未全绿，不能声称 Week6 全部质量检查通过。 |
| F012 | MEDIUM | FAIL | Task tracking | tasks/completed/ 缺失 | 任务完成记录无法按审计要求从仓库结构核验。 |
| F013 | LOW | PASS_WITH_RISK | Security | 未发现真实密钥，但存在本地 docker-compose 测试密码和测试用假 secret 命中 | 未发现真实凭据泄漏；docker-compose 密码应仅作为本地测试凭据。 |

## Immediate Blockers

1. No git commits, remote, or tags.
2. Default DB stale and unusable with current migration chain.
3. Week6 projection loses SnapshotRecord provenance.
4. Week6 projection is not a full integrated product dataset.
5. Human review remains open across all real provider data.

## Week7 Risk

Starting Week7 product mapping or sales reasoning now would convert readiness artifacts into unsupported competitive claims. That would violate the evidence-first project policy.
