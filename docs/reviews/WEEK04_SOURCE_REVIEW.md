# Week 4 AWS Source Review

## Scope

Week 4 adds AWS commercial global (`provider_code=aws`,
`cloud_partition=aws`) official sources for Amazon EC2 and Amazon S3. The review
covers only public pages that can be fetched without authentication.

## Adopted EC2 Sources

| Source ID | URL | Purpose |
| --- | --- | --- |
| `aws_ec2_product_page` | `https://aws.amazon.com/ec2/` | Product name and description evidence |
| `aws_ec2_instance_types_user_guide` | `https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/instance-types.html` | EC2 instance type scope |
| `aws_ec2_instance_type_specs` | `https://docs.aws.amazon.com/ec2/latest/instancetypes/ec2-instance-type-specifications.html` | Specification index |
| `aws_ec2_general_purpose_specs` | `https://docs.aws.amazon.com/ec2/latest/instancetypes/gp.html` | General purpose instance table parsing |
| `aws_ec2_compute_optimized_specs` | `https://docs.aws.amazon.com/ec2/latest/instancetypes/co.html` | Compute optimized instance table parsing |
| `aws_ec2_network_bandwidth` | `https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/ec2-instance-network-bandwidth.html` | Network semantics evidence |
| `aws_ec2_regions` | `https://docs.aws.amazon.com/general/latest/gr/ec2-service.html` | Commercial Region evidence |
| `aws_ec2_service_quotas` | `https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/ec2-resource-limits.html` | Quota source registration |
| `aws_ec2_sla` | `https://aws.amazon.com/compute/sla/` | EC2 availability SLA evidence |

## Adopted S3 Sources

| Source ID | URL | Purpose |
| --- | --- | --- |
| `aws_s3_product_page` | `https://aws.amazon.com/s3/` | Product name and description evidence |
| `aws_s3_user_guide` | `https://docs.aws.amazon.com/AmazonS3/latest/userguide/` | User Guide scope evidence |
| `aws_s3_storage_classes` | `https://docs.aws.amazon.com/AmazonS3/latest/userguide/storage-class-intro.html` | Storage class table parsing |
| `aws_s3_regions` | `https://docs.aws.amazon.com/general/latest/gr/s3.html` | Commercial Region evidence |
| `aws_s3_multipart_upload` | `https://docs.aws.amazon.com/AmazonS3/latest/userguide/mpuoverview.html` | Multipart upload and object-size evidence |
| `aws_s3_versioning` | `https://docs.aws.amazon.com/AmazonS3/latest/userguide/Versioning.html` | Versioning support evidence |
| `aws_s3_lifecycle` | `https://docs.aws.amazon.com/AmazonS3/latest/userguide/object-lifecycle-mgmt.html` | Lifecycle support evidence |
| `aws_s3_replication` | `https://docs.aws.amazon.com/AmazonS3/latest/userguide/replication.html` | Replication support evidence |
| `aws_s3_object_lock` | `https://docs.aws.amazon.com/AmazonS3/latest/userguide/object-lock.html` | Object Lock support evidence |
| `aws_s3_encryption_kms` | `https://docs.aws.amazon.com/AmazonS3/latest/userguide/UsingKMSEncryption.html` | SSE-KMS evidence |
| `aws_s3_event_notifications` | `https://docs.aws.amazon.com/AmazonS3/latest/userguide/EventNotifications.html` | Event notification evidence |
| `aws_s3_static_website` | `https://docs.aws.amazon.com/AmazonS3/latest/userguide/EnableWebsiteHosting.html` | Static website evidence |
| `aws_s3_sla` | `https://aws.amazon.com/s3/sla/` | S3 SLA evidence |

## Registered But Disabled

| Source ID | URL | Reason |
| --- | --- | --- |
| `aws_ec2_pricing_on_demand` | `https://aws.amazon.com/ec2/pricing/on-demand/` | Pricing/TCO is out of Week 4 scope |
| `aws_s3_pricing` | `https://aws.amazon.com/s3/pricing/` | Pricing/TCO is out of Week 4 scope |

## Rejected Or Deferred

- AWS China documentation and `cn-*` endpoints: deferred because they belong to
  the `aws-cn` partition, not commercial global.
- AWS GovCloud documentation and `us-gov-*` endpoints: deferred because they
  belong to the `aws-us-gov` partition.
- AWS console pages, calculators that require browser/session state, API calls
  requiring credentials, private account quota pages, customer data, and pricing
  APIs: rejected for Week 4.
- AWS Marketplace, blog, community, re:Post, and third-party comparison pages:
  rejected because Week 4 accepts official primary product, documentation, and
  SLA sources only.

## Robots And Terms Review

- `docs.aws.amazon.com/robots.txt` disallows search and legacy API-version
  paths. The adopted `/latest/` documentation and `/general/latest/` paths are
  not disallowed.
- `aws.amazon.com/robots.txt` blocks search, blogs, campaign, and form paths.
  The adopted `/ec2/`, `/s3/`, `/compute/sla/`, and `/s3/sla/` paths are not
  disallowed.
- Fetch cadence uses a conservative per-source interval and no authentication,
  cookies, console, or browser-rendered pages.

## Acceptance Results

- AWS registry validation: 24 valid sources, 2 disabled pricing sources, 0
  configuration errors.
- Official snapshots captured: 22 enabled sources.
- Raw snapshot validation: 44 total snapshots checked across existing Huawei and
  AWS raw data, 0 errors.
- Partition validation: 0 AWS commercial partition violations.
- Evidence link validation: 0 missing evidence links.
