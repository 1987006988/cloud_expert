# Source Policy

## Purpose

The project is evidence-first. A product fact, price, mapping, or claim must not
enter customer-facing workflows unless it can be traced back to a registered
source, an immutable raw snapshot, a `SourceDocument`, and later an `Evidence`
record.

Week 2 only registers sources and captures raw snapshots. It does not extract
real product facts, price facts, mappings, rankings, sales scripts, or customer
recommendations.

## Allowed Source Classes

- Public official provider pages that can be fetched without authentication.
- Public official documentation, product pages, service catalogs, price pages,
  API reference pages, and changelog pages.
- Public PDF or JSON resources from an approved official domain.
- Synthetic `.invalid` fixture sources used only for tests and local
  end-to-end validation.

## Disallowed Source Classes

- Pages requiring login, cookies tied to a user account, captcha, browser-only
  rendering, or personal session state.
- Partner portals, customer portals, private quotes, account-specific prices, or
  internal commercial documents.
- Pages whose terms review marks automated collection as disallowed or requiring
  manual review.
- Any customer data, account identifiers, credentials, tokens, private keys, or
  personal information.
- Sources that require bypassing robots, network controls, redirects, or access
  restrictions.

## Registry Requirements

Each registry record must include:

- Stable `source_id`.
- Provider code, market mode, optional product code, title, source type, and
  authority level.
- Optional `cloud_partition` when a provider has multiple public partitions
  such as AWS commercial (`aws`), AWS China (`aws-cn`), or AWS GovCloud
  (`aws-us-gov`), and Aliyun China public cloud (`aliyun_public_cn`).
- Canonical URL and expected content type.
- Domain policy with explicit allowed domains and redirect rules.
- Fetch policy for timeout, retry count, rate limit, and maximum content size.
- Storage policy requiring immutable version retention.
- Review metadata for terms, robots, automation allowance, and owner notes.

`fixture_response_path` is only allowed for `.invalid` fixture URLs. Real source
records must not point at fixture files.

## Cloud Partition Rule

Provider partitions must not be merged. A source registered with
`cloud_partition=aws` can support only AWS commercial global facts. AWS China
and AWS GovCloud sources require separate registry records, source review, and
partition validation before use.

A source registered with `cloud_partition=aliyun_public_cn` can support only
Aliyun domestic public-cloud facts. China Hong Kong, overseas, government,
finance, special-cloud, console, account-specific, and international
`alibabacloud.com` sources require separate review and must not be mixed into
the domestic Aliyun baseline.

## Fetch Safety

The fetcher blocks:

- URL schemes other than `http` and `https`.
- Username or password in URLs.
- Localhost, private IP ranges, link-local metadata addresses, and dangerous
  non-standard ports.
- Redirects outside the registered domain policy.
- Oversized, empty, or unexpected MIME responses.

Response headers are sanitized before storage. Sensitive header names and values
such as cookies, authorization tokens, and API keys are redacted.

## Review Gate

`terms_review_status=approved` is required before an automated fetch of a real
source. If a source is `manual_only`, `requires_authentication`, or
`requires_browser`, the Week 2 HTTP fetcher must block it and create only a
failed or blocked ingestion run record.
