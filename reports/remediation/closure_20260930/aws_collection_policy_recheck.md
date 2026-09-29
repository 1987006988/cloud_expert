# AWS Collection Policy Recheck

Checked at 2026-09-29T18:51:29Z. Engineering acquisition decision, not legal advice.

## Observed Authorities

- https://aws.amazon.com/terms/ (Site Terms dated June 4, 2025), License and
  Site Access: the ordinary website license excludes automated extraction;
  technical documentation on docs.aws.amazon.com has a separate CC-BY-SA-4.0
  license. Preserve attribution and license obligations for retained documents.
- https://aws.amazon.com/robots.txt and https://docs.aws.amazon.com/robots.txt:
  robots paths are a separate collection condition, not a content-use license.
- https://docs.aws.amazon.com/awsaccountbilling/latest/aboutv2/using-the-aws-price-list-bulk-api-fetching-price-list-files-manually.html:
  the public service, region and versioned price-list download paths are
  expressly documented. This acquisition permission is not price approval,
  account-discount authority, customer-output permission or a tax conclusion.

## Corrections

The previous approved EC2 On-Demand and S3 website registry entries relied on
public-official-page visibility, not documented extraction permission. Their
collection is now retired. Existing raw files, SourceDocument, Evidence and
PriceSnapshot history remain unchanged. Four newly discovered ordinary website
policy candidates (EBS pricing, EBS volume types, public IPv4 pricing, Support
FAQ) are also not approved for collection. No new fetch of these four was made.

The earlier 18/18 price-evidence validation remains an authentic historical
result under its then-current registry. It must NOT be used as present approval
of AWS PriceSnapshots 13-18: their supporting website-policy acquisition no
longer passes the current source check. They need licensed replacement policy
Evidence and controlled supersession/revalidation before consumption.

Five documented Price List download routes were approved with a 2 MiB hard
ceiling. Actual captures are SnapshotRecords 100-104: AWSDataTransfer regional
catalog, AmazonVPC regional catalog, service index and both region indexes.
These create no new cloud Product entity and no new approved price or TCO.

## Required Follow-Up

1. Capture the licensed AWS technical-documentation equivalents for units,
   billing periods, tax scope, support and shared allowances.
2. Revalidate exact statement scope; a usage-metric definition must not silently
   become an unrelated billing rule.
3. Preserve old price history and bind replacement policy evidence explicitly.
   Do not mutate old excerpts, invent a vendor price-expiry date or mark a
   deterministic source-policy block as a model approval.
4. Re-run price consumers and Gates. Unrelated domestic work is not evidence
   that the AWS component chain passed.
