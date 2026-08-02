from pathlib import Path

import httpx

from cloud_expert.ingestion.registry.schemas import SourceRegistryEntry
from cloud_expert.ingestion.user_agents import resolve_request_headers


def build_http_client(entry: SourceRegistryEntry, *, env: str = "development") -> httpx.Client:
    headers = resolve_request_headers(entry.fetch_policy.user_agent_profile, env=env)
    if entry.fixture_response_path:
        fixture_path = Path(entry.fixture_response_path)
        if entry.registry_file is not None and not fixture_path.is_absolute():
            fixture_path = entry.registry_file.parent / fixture_path
        content = fixture_path.read_bytes()

        def _handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                entry.fixture_response_status,
                headers={
                    "Content-Type": entry.fixture_response_content_type
                    or entry.expected_content_type[0],
                    "Content-Length": str(len(content)),
                },
                content=content,
                request=request,
            )

        return httpx.Client(transport=httpx.MockTransport(_handler), headers=headers)
    return httpx.Client(headers=headers, follow_redirects=False)
