# Mapping Architecture

Week 7 mapping creates internal `MappingCandidate` rows between Huawei Cloud,
AWS, and Aliyun entities. A candidate is not an approved mapping by itself.

Key rules:

- Mapping is versioned by `MappingRuleSet`.
- Candidate scores are technical similarity signals only.
- `MappingFieldComparison` records field-level comparability, scope, qualifier,
  evidence, and blocking status.
- Automatic mapping approval is prohibited. Pending review data may be used only
  for internal engineering outputs.
- Customer-facing output requires human-reviewed mapping and eligible evidence
  packages.
