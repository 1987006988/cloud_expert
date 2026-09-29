import hashlib
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from cloud_expert.pricing import huawei_api as api


def query() -> api.PricingQuery:
    return api.PricingQuery.model_validate(
        {
            "product_infos": [
                {
                    "id": "synthetic-1",
                    "cloud_service_type": "synthetic.service",
                    "resource_type": "synthetic.resource",
                    "resource_spec": "synthetic.spec",
                    "region": "cn-test-1",
                    "usage_factor": "synthetic_duration",
                    "usage_value": 1,
                    "usage_measure_id": 4,
                    "subscription_num": 1,
                }
            ]
        }
    )


def response() -> dict:
    return {
        "currency": "CNY",
        "product_rating_results": [
            {"id": "synthetic-1", "official_website_amount": "1.25", "measure_id": 1}
        ],
    }


def test_no_credentials_are_disclosed(monkeypatch):
    monkeypatch.setenv("HUAWEICLOUD_AUTH_TOKEN", "synthetic-token")
    monkeypatch.delenv("HUAWEICLOUD_PROJECT_ID", raising=False)
    assert api.credential_status() == {
        "HUAWEICLOUD_AUTH_TOKEN": True,
        "HUAWEICLOUD_PROJECT_ID": False,
    }
    credentials = api.LocalCredentials(token="synthetic-token", project_id="synthetic-project")
    assert "synthetic-token" not in repr(credentials)
    assert "synthetic-project" not in credentials.model_dump_json()
    for value in ("", " ", "a\nb", "a b"):
        with pytest.raises(ValidationError):
            api.LocalCredentials(token=value, project_id="synthetic-project")


def test_query_contract_rejects_wrong_market_duplicates_and_credentials():
    payload = query().model_dump()
    payload["product_infos"][0]["region"] = "eu-west-1"
    with pytest.raises(ValidationError):
        api.PricingQuery.model_validate(payload)
    payload = query().model_dump()
    payload["product_infos"].append(payload["product_infos"][0])
    with pytest.raises(ValidationError):
        api.PricingQuery.model_validate(payload)
    with pytest.raises(ValidationError):
        api.PricingQuery.model_validate({**query().model_dump(), "token": "secret"})


def test_only_official_endpoint_used(monkeypatch):
    actual_client = httpx.Client

    def handler(request):
        assert request.method == "POST"
        assert str(request.url) == api.ENDPOINT
        assert request.headers["X-Auth-Token"] == "synthetic-token"
        body = json.loads(request.content)
        assert body["project_id"] == "synthetic-project"
        assert "token" not in body
        return httpx.Response(200, json=response())

    def client(**kwargs):
        assert kwargs == {"timeout": 30, "follow_redirects": False, "trust_env": False}
        return actual_client(**kwargs, transport=httpx.MockTransport(handler))

    monkeypatch.setattr(api.httpx, "Client", client)
    result = api.query_prices(
        query(), api.LocalCredentials(token="synthetic-token", project_id="synthetic-project")
    )
    assert json.loads(result) == response()


@pytest.mark.parametrize("status", [301, 302, 400, 401, 403, 429, 500])
def test_errors_and_redirects_do_not_expose_bodies(monkeypatch, status):
    actual_client = httpx.Client
    monkeypatch.setattr(
        api.httpx,
        "Client",
        lambda **kwargs: actual_client(
            **kwargs,
            transport=httpx.MockTransport(
                lambda req: httpx.Response(
                    status,
                    text="sensitive-response",
                    headers={"Location": "https://example.invalid"},
                )
            ),
        ),
    )
    with pytest.raises(api.PricingQueryError) as exc:
        api.query_prices(query(), api.LocalCredentials(token="token", project_id="project"))
    assert str(exc.value) == f"Official pricing API HTTP {status}"


def test_size_and_connection_failures_are_safe(monkeypatch):
    actual_client = httpx.Client
    monkeypatch.setattr(api, "MAX_RESPONSE_BYTES", 1)
    monkeypatch.setattr(
        api.httpx,
        "Client",
        lambda **kwargs: actual_client(
            **kwargs,
            transport=httpx.MockTransport(lambda req: httpx.Response(200, json=response())),
        ),
    )
    with pytest.raises(api.PricingQueryError, match="size limit"):
        api.query_prices(query(), api.LocalCredentials(token="token", project_id="project"))

    def fail(request):
        raise httpx.ConnectError("sensitive-error-body")

    monkeypatch.setattr(
        api.httpx,
        "Client",
        lambda **kwargs: actual_client(**kwargs, transport=httpx.MockTransport(fail)),
    )
    with pytest.raises(api.PricingQueryError, match="no credentials logged") as exc:
        api.query_prices(query(), api.LocalCredentials(token="token", project_id="project"))
    assert "sensitive" not in str(exc.value)


@pytest.mark.parametrize(
    "payload",
    [
        [],
        {"error_code": "failure"},
        {"product_rating_results": "bad"},
        {"product_rating_results": [42]},
        {"product_rating_results": []},
        {"product_rating_results": [{"id": "mismatch"}]},
        {**response(), "currency": "USD"},
        {"product_rating_results": response()["product_rating_results"] * 2},
        {"product_rating_results": [{"id": "synthetic-1", "official_website_amount": "NaN"}]},
        {
            "product_rating_results": [
                {"id": "synthetic-1", "official_website_amount": -1, "measure_id": 1}
            ]
        },
    ],
)
def test_invalid_responses_fail_closed(payload):
    with pytest.raises(api.PricingQueryError, match="schema/correlation"):
        api.validate_response(json.dumps(payload).encode(), query())


def test_staging_preserves_exact_bytes_and_never_invents_evidence(tmp_path):
    raw = json.dumps(response()).encode()
    first = api.stage_response(raw, query(), tmp_path)
    second = api.stage_response(raw, query(), tmp_path)
    assert first["directory"] != second["directory"]
    assert first["database_written"] is False
    assert first["response_sha256"] == hashlib.sha256(raw).hexdigest()
    directory = Path(first["directory"])
    assert (directory / "response.bin").read_bytes() == raw
    metadata = json.loads((directory / "metadata.json").read_text())
    assert metadata["external_transfer_allowed"] is False
    assert "project_id" not in metadata["query"]
    assert metadata["promotion_status"] == "pending_source_document_and_evidence"
