# Week11 人工审核说明

生成时间：2026-09-28（Asia/Shanghai）

## 文件

- `week11_mapping_review.csv`：414 条最新跨厂商映射候选。
- `week10_decision_review.csv`：最新决策结果审核样本，共 120 条。
- `week11_gate_validation_results.json`：本次 Gate 判定及阻断项。

## Mapping 审核

请只填写以下三列，不要修改主键和机器生成字段：

- `review_result`：`approved`、`rejected` 或 `needs_correction`。
- `reviewer`：真实审核人标识，不得为空。
- `reviewer_notes`：说明接受条件、拒绝原因或需要修正的字段。

审核时需核对 `source_evidence`、`target_evidence`、`blocking_reasons` 和
`conditions`。存在关键字段缺失或证据不足时，不应批准。

## DecisionResult 审核

请只填写以下三列，不要修改 `decision_result_id` 及机器生成字段：

- `review_result`：`internally_approved`、`rejected` 或 `corrected`。
- `reviewer`：真实审核人标识，不得为空。
- `reviewer_notes`：说明接受/拒绝的假设、范围、风险和修正要求。

当前结果均为 `internal_only`。价格不完整、映射未审核或证据未达到客户输出条件的
记录不得批准为客户可用结论。审核并不自动消除上游数据缺口。

## 完成后

保留原文件名，将两个 CSV 放回同一目录。后续执行受控导入时会保存导入批次、文件
哈希、审核人、审核时间和变更前后快照，然后重新生成 Evidence、Decision 并执行
Week11 Gate。
