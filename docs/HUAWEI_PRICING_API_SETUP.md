# Huawei Read-Only Pricing API Setup

The owner authorized the official read-only API route on 2026-09-29. Actual
ECS and OBS queries have succeeded through signed-in official API Explorer.
No Huawei credential was exported to the agent process environment; unattended
Token-client access is separate and remains unconfigured. No IAM account or
permission was created. See the capture report in
`reports/remediation/closure_20260929/huawei_api_capture.md`.

## Local Credentials

Use an existing, narrowly authorized IAM identity, not an administrator identity.
The official `ListOnDemandResourceRatings` API accepts an IAM Token or AK/SK.
This adapter supports Token only and never calls order, purchase, resource
creation, or permission-changing APIs. Identity-policy authorization documented
for this API is the read action `billing:contract:viewDiscount`. Confirm the
identity has the required permission in your own account; this project does not
grant it automatically.

Official reference: https://support.huaweicloud.com/api-oce/bcloud_01001.html

The Token and regional project ID must be entered on this machine, not in chat.
Use the hidden interactive prompts below. Alternatively set the process
environment variables `HUAWEICLOUD_AUTH_TOKEN` and `HUAWEICLOUD_PROJECT_ID`.
The application does not automatically read `.env` files. Do not place real
credentials in command arguments, request JSON, version control, or reports.

## Query File

Create a local JSON file under `test_outputs/` with `product_infos` and optional
`inquiry_precision: 1`. Each product needs `id`, `cloud_service_type`,
`resource_type`, `resource_spec`, `region`, `usage_factor`, `usage_value`,
`usage_measure_id`, and `subscription_num`. Use verified product specification
and billing-unit codes from official evidence/API documentation. Do not infer
codes or copy example prices as real product facts. This initial adapter is for
Huawei China regions only; international billing must use a separate approved
source and market context. Do not include project IDs or Tokens in the file.

From the repository terminal:

```powershell
.\.venv312\Scripts\python.exe scripts/query_huawei_prices.py --check-config
.\.venv312\Scripts\python.exe scripts/query_huawei_prices.py --interactive --request test_outputs/huawei_price_query.json
```

The command uses only the fixed official HTTPS on-demand pricing endpoint.
Redirects and environment-provided proxies are disabled. Token input is hidden;
errors omit request/response bodies and secret values. This does not verify that
the Token itself has only read permissions; the account owner must ensure that.

## Evidence Boundary

Successful queries produce a new local run directory under
`test_outputs/huawei_pricing_api/`. It contains the exact response bytes,
SHA-256, capture time, and product query without project ID or request headers.
This directory is Git-ignored. Responses can include account-specific discounts;
do not transfer these files to OpenAI or other external services. Retain them
locally for subsequent validation.

The Token CLI staging step does **not** create a SourceDocument, Evidence, PriceSKU, or
PriceSnapshot. Nor does it approve collection rules or change any Gate. Before
promotion, register the authenticated source, verify account usage rights,
associate response IDs with the request and source evidence, distinguish public
list amounts from discounts, and establish units, quantity range, currency, tax,
market, and freshness. Never extrapolate a single quoted quantity into a tiered
unit price. Then ingest through the controlled evidence pipeline and rerun TCO,
Decision, model review, and downstream Gates.

## Controlled API Explorer Import

`scripts/import_huawei_api_ui_capture.py` separately imports approved, scoped
API Explorer response copies into immutable snapshots, SourceDocument and
Evidence. The import explicitly labels clipboard capture, validates product
scope and response IDs, excludes account discounts from excerpts, and rejects
reuse of identical response bytes with a different query. It cannot create a
PriceSKU or PriceSnapshot. Existing successful imports are idempotent; keep
their original query and capture timestamp. Do not include the regional
project ID in the query envelope or copy request headers.
