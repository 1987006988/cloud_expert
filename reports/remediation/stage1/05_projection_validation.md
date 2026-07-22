# Projection Validation

`scripts/validate_week06_projection.py` passed on the rebuilt projection.

Key counts:

- providers: 3
- products: 6
- source documents: 67
- snapshot records: 67
- evidence rows: 14113
- product specifications: 10412
- normalized specifications: 10172
- product families: 299
- service tiers: 17
- regions: 53
- availability rows: 102
- availability zones: 62
- zone availability rows: 62
- product SLA rows: 13
- parsed field candidates: 14184
- parsing runs: 67
- ingestion runs: 89
- review items: 1441

Sample chain checks all passed:

- `huawei_cloud/ecs`: 10/10
- `aws/ec2`: 10/10
- `aliyun/ecs`: 10/10
- `huawei_cloud/obs`: 5/5
- `aws/s3`: 5/5
- `aliyun/oss`: 5/5
