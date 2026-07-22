import time
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from pathlib import Path

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from cloud_expert.database.enums import (
    ChangeStatus,
    IngestionRunStatus,
    IngestionRunType,
)
from cloud_expert.database.models.ingestion import IngestionRun
from cloud_expert.database.models.provider import Provider
from cloud_expert.database.models.snapshot import SnapshotRecord
from cloud_expert.database.models.source import SourceDocument
from cloud_expert.ingestion.client import build_http_client
from cloud_expert.ingestion.content.inspector import inspect_content
from cloud_expert.ingestion.exceptions import (
    DNSIngestionError,
    EmptyContentError,
    FileTooLargeError,
    HttpStatusError,
    IngestionError,
    MimeMismatchError,
    RequiresAuthenticationError,
    RequiresBrowserError,
    SSLIngestionError,
    TimeoutIngestionError,
)
from cloud_expert.ingestion.rate_limit import DomainRateLimiter
from cloud_expert.ingestion.registry.schemas import SourceRegistryEntry
from cloud_expert.ingestion.result import HttpFetchResult, IngestionOutcome
from cloud_expert.ingestion.retry import bounded_retry_count, should_retry_http_status
from cloud_expert.ingestion.security.domain_policy import assert_url_allowed_by_policy
from cloud_expert.ingestion.security.redirect_validator import validate_redirect_location
from cloud_expert.ingestion.security.url_validator import validate_fetch_url
from cloud_expert.ingestion.storage.snapshot_store import SnapshotStore, StoredSnapshot


def _now() -> datetime:
    return datetime.now(UTC)


def _duration_ms(start: datetime, end: datetime) -> int:
    return int((end - start).total_seconds() * 1000)


class SourceFetcher:
    def __init__(
        self,
        *,
        client: httpx.Client | None = None,
        snapshot_store: SnapshotStore | None = None,
    ) -> None:
        self.client = client
        self.snapshot_store = snapshot_store or SnapshotStore()

    def fetch(
        self,
        entry: SourceRegistryEntry,
        *,
        session: Session | None = None,
        run_type: str = IngestionRunType.MANUAL.value,
        dry_run: bool = False,
        force: bool = False,
    ) -> IngestionOutcome:
        started_at = _now()
        requested_url = entry.url
        try:
            self._preflight(entry)
            if dry_run:
                completed = _now()
                outcome = IngestionOutcome(
                    source_id=entry.source_id,
                    status=IngestionRunStatus.SKIPPED.value,
                    requested_url=requested_url,
                    final_url=requested_url,
                    duration_ms=_duration_ms(started_at, completed),
                )
                self._record_run(session, entry, outcome, started_at, completed, run_type)
                return outcome

            http_result = self._fetch_http(entry, force=force)
            if http_result.status_code == 304:
                completed = _now()
                outcome = IngestionOutcome(
                    source_id=entry.source_id,
                    status=IngestionRunStatus.UNCHANGED.value,
                    requested_url=requested_url,
                    final_url=http_result.final_url,
                    http_status=304,
                    retry_count=http_result.retry_count,
                    duration_ms=http_result.duration_ms,
                    change_status=ChangeStatus.UNCHANGED.value,
                )
                self._record_run(session, entry, outcome, started_at, completed, run_type)
                return outcome

            self._validate_response(entry, http_result)
            _formatted_content, content_metadata = inspect_content(
                http_result.content_type,
                http_result.content,
                http_result.encoding,
            )
            stored = self.snapshot_store.store(
                entry=entry,
                requested_url=requested_url,
                final_url=http_result.final_url,
                http_status=http_result.status_code,
                content_type=http_result.content_type,
                content=http_result.content,
                response_headers=http_result.headers,
                content_metadata=content_metadata,
                fetch_duration_ms=http_result.duration_ms,
                captured_at=http_result.completed_at,
            )
            snapshot_record_id = self._record_success(session, entry, http_result, stored)
            status = (
                IngestionRunStatus.SUCCEEDED.value
                if stored.created
                else IngestionRunStatus.UNCHANGED.value
            )
            outcome = IngestionOutcome(
                source_id=entry.source_id,
                status=status,
                requested_url=requested_url,
                final_url=http_result.final_url,
                http_status=http_result.status_code,
                content_type=http_result.content_type,
                bytes_downloaded=http_result.content_length_bytes,
                retry_count=http_result.retry_count,
                duration_ms=http_result.duration_ms,
                snapshot_id=stored.manifest.snapshot_id,
                snapshot_record_id=snapshot_record_id,
                change_status=stored.change_report.change_status,
                manifest_path=str(stored.manifest_path),
                changes=[change.model_dump() for change in stored.change_report.changes],
            )
            self._record_run(session, entry, outcome, started_at, _now(), run_type)
            return outcome
        except IngestionError as exc:
            return self._failure_outcome(session, entry, exc, started_at, requested_url, run_type)
        except httpx.TimeoutException as exc:
            return self._failure_outcome(
                session,
                entry,
                TimeoutIngestionError(str(exc)),
                started_at,
                requested_url,
                run_type,
            )
        except httpx.ConnectError as exc:
            return self._failure_outcome(
                session,
                entry,
                DNSIngestionError(str(exc)),
                started_at,
                requested_url,
                run_type,
            )
        except httpx.TransportError as exc:
            return self._failure_outcome(
                session,
                entry,
                SSLIngestionError(str(exc)),
                started_at,
                requested_url,
                run_type,
            )
        except Exception as exc:
            return self._failure_outcome(
                session,
                entry,
                IngestionError(str(exc)),
                started_at,
                requested_url,
                run_type,
            )

    def _preflight(self, entry: SourceRegistryEntry) -> None:
        if entry.requires_authentication:
            msg = "source requires authentication"
            raise RequiresAuthenticationError(msg)
        if entry.requires_browser:
            msg = "browser-rendered sources are not supported in Week 2"
            raise RequiresBrowserError(msg)
        if not entry.allow_automated_fetch:
            msg = "automated fetch is disabled for this source"
            raise RequiresAuthenticationError(msg)
        validate_fetch_url(entry.url)
        assert_url_allowed_by_policy(
            entry.url,
            entry.domain_policy.allowed_domains,
            allow_subdomains=entry.domain_policy.allow_subdomains,
        )

    def _fetch_http(self, entry: SourceRegistryEntry, *, force: bool) -> HttpFetchResult:
        client = self.client or build_http_client(entry)
        close_client = self.client is None
        limiter = DomainRateLimiter(entry.fetch_policy.min_interval_seconds)
        url = entry.url
        headers: dict[str, str] = {}
        if not force:
            latest = self.snapshot_store.latest_manifest(entry)
            if latest:
                latest_headers = latest[0].content_metadata.get("response_headers", {})
                if isinstance(latest_headers, dict):
                    etag = latest_headers.get("ETag") or latest_headers.get("etag")
                    modified = latest_headers.get("Last-Modified") or latest_headers.get(
                        "last-modified"
                    )
                    if isinstance(etag, str):
                        headers["If-None-Match"] = etag
                    if isinstance(modified, str):
                        headers["If-Modified-Since"] = modified
        try:
            retry_count = 0
            max_retries = bounded_retry_count(entry.fetch_policy.max_retries)
            while True:
                limiter.wait(url)
                try:
                    result = self._download_with_redirects(client, entry, url, headers)
                except httpx.TimeoutException:
                    if retry_count >= max_retries:
                        raise
                    retry_count += 1
                    time.sleep(entry.fetch_policy.retry_backoff_seconds * retry_count)
                    continue
                if should_retry_http_status(result.status_code) and retry_count < max_retries:
                    retry_count += 1
                    retry_after = result.headers.get("Retry-After")
                    sleep_seconds = entry.fetch_policy.retry_backoff_seconds * retry_count
                    if retry_after:
                        try:
                            sleep_seconds = min(float(retry_after), 10.0)
                        except ValueError:
                            parsed_retry_at = parsedate_to_datetime(retry_after)
                            sleep_seconds = min(
                                max((parsed_retry_at - _now()).total_seconds(), 0),
                                10.0,
                            )
                    time.sleep(sleep_seconds)
                    continue
                return result.__class__(**{**result.__dict__, "retry_count": retry_count})
        finally:
            if close_client:
                client.close()

    def _download_with_redirects(
        self,
        client: httpx.Client,
        entry: SourceRegistryEntry,
        url: str,
        headers: dict[str, str],
    ) -> HttpFetchResult:
        current_url = url
        for _redirect_index in range(6):
            started_at = _now()
            with client.stream(
                "GET",
                current_url,
                headers=headers,
                timeout=httpx.Timeout(
                    timeout=entry.fetch_policy.timeout_seconds,
                    connect=entry.fetch_policy.connect_timeout_seconds,
                    read=entry.fetch_policy.read_timeout_seconds,
                    write=entry.fetch_policy.timeout_seconds,
                ),
                follow_redirects=False,
            ) as response:
                if response.status_code in {301, 302, 303, 307, 308}:
                    location = response.headers.get("Location")
                    if not location:
                        msg = "redirect response missing Location header"
                        raise HttpStatusError(msg)
                    current_url = validate_redirect_location(
                        current_url, location, entry.domain_policy
                    )
                    continue
                chunks: list[bytes] = []
                total = 0
                for chunk in response.iter_bytes():
                    total += len(chunk)
                    if total > entry.fetch_policy.max_content_length_bytes:
                        msg = "download exceeded max_content_length_bytes"
                        raise FileTooLargeError(msg)
                    chunks.append(chunk)
                completed_at = _now()
                content_type = response.headers.get("Content-Type", "").split(";", 1)[0].lower()
                return HttpFetchResult(
                    requested_url=url,
                    final_url=str(response.url),
                    status_code=response.status_code,
                    headers=dict(response.headers.items()),
                    content=b"".join(chunks),
                    content_type=content_type,
                    encoding=response.encoding,
                    started_at=started_at,
                    completed_at=completed_at,
                    duration_ms=_duration_ms(started_at, completed_at),
                    retry_count=0,
                )
        msg = "too many redirects"
        raise HttpStatusError(msg)

    def _validate_response(self, entry: SourceRegistryEntry, result: HttpFetchResult) -> None:
        if result.status_code >= 400:
            msg = f"HTTP error: {result.status_code}"
            raise HttpStatusError(msg)
        if not result.content:
            msg = "response content is empty"
            raise EmptyContentError(msg)
        if result.content_type not in entry.expected_content_type:
            msg = f"content type {result.content_type!r} not in expected {entry.expected_content_type}"
            raise MimeMismatchError(msg)
        if result.content_length_bytes > entry.fetch_policy.max_content_length_bytes:
            msg = "response content exceeds max size"
            raise FileTooLargeError(msg)

    def _ensure_provider(self, session: Session, provider_code: str) -> Provider:
        provider = session.scalar(select(Provider).where(Provider.code == provider_code))
        if provider is None:
            is_huawei_cloud = provider_code == "huawei_cloud"
            provider = Provider(
                code=provider_code,
                name="Huawei Cloud Domestic"
                if is_huawei_cloud
                else f"Registry provider {provider_code}",
                display_name="Huawei Cloud" if is_huawei_cloud else provider_code,
                provider_type="cloud" if is_huawei_cloud else "registry",
                official_website="https://www.huaweicloud.com/" if is_huawei_cloud else None,
                is_active=True,
            )
            session.add(provider)
            session.flush()
        return provider

    def _record_success(
        self,
        session: Session | None,
        entry: SourceRegistryEntry,
        result: HttpFetchResult,
        stored: StoredSnapshot,
    ) -> int | None:
        if session is None:
            return None
        provider = self._ensure_provider(session, entry.provider_code)
        source_document = session.scalar(
            select(SourceDocument).where(
                SourceDocument.url == result.final_url,
                SourceDocument.content_hash == stored.manifest.content_sha256,
            )
        )
        if source_document is None:
            source_document = SourceDocument(
                provider_id=provider.id,
                source_type=str(entry.source_type),
                title=entry.title,
                url=result.final_url,
                cloud_partition=entry.cloud_partition,
                language=entry.language,
                authority_level=str(entry.authority_level),
                captured_at=result.completed_at,
                content_hash=stored.manifest.content_sha256,
                storage_path=stored.manifest.storage_path,
                mime_type=result.content_type,
                http_status=result.status_code,
                is_current=True,
            )
            session.add(source_document)
            session.flush()

        snapshot_record = session.scalar(
            select(SnapshotRecord).where(
                SnapshotRecord.source_id == entry.source_id,
                SnapshotRecord.content_hash == stored.manifest.content_sha256,
            )
        )
        if snapshot_record is None:
            previous_record = session.scalar(
                select(SnapshotRecord)
                .where(
                    SnapshotRecord.source_id == entry.source_id, SnapshotRecord.is_current.is_(True)
                )
                .order_by(SnapshotRecord.captured_at.desc())
            )
            for current_record in session.scalars(
                select(SnapshotRecord).where(SnapshotRecord.source_id == entry.source_id)
            ):
                current_record.is_current = False
            snapshot_record = SnapshotRecord(
                source_document_id=source_document.id,
                source_id=entry.source_id,
                content_hash=stored.manifest.content_sha256,
                storage_path=stored.manifest.storage_path,
                manifest_path=str(
                    stored.manifest_path.relative_to(Path(self.snapshot_store.raw_data_dir))
                ),
                content_type=result.content_type,
                content_length_bytes=result.content_length_bytes,
                captured_at=result.completed_at,
                previous_snapshot_id=previous_record.id if previous_record else None,
                change_status=stored.manifest.change_status,
                is_current=True,
            )
            session.add(snapshot_record)
            session.flush()
        session.commit()
        return snapshot_record.id

    def _record_run(
        self,
        session: Session | None,
        entry: SourceRegistryEntry,
        outcome: IngestionOutcome,
        started_at: datetime,
        completed_at: datetime,
        run_type: str,
    ) -> None:
        if session is None:
            return
        run = IngestionRun(
            source_id=entry.source_id,
            run_type=run_type,
            started_at=started_at,
            completed_at=completed_at,
            status=outcome.status,
            requested_url=outcome.requested_url,
            final_url=outcome.final_url,
            http_status=outcome.http_status,
            content_type=outcome.content_type,
            bytes_downloaded=outcome.bytes_downloaded,
            retry_count=outcome.retry_count,
            duration_ms=outcome.duration_ms,
            snapshot_id=outcome.snapshot_record_id,
            error_code=outcome.error_code,
            error_message=outcome.error_message,
        )
        session.add(run)
        session.commit()

    def _failure_outcome(
        self,
        session: Session | None,
        entry: SourceRegistryEntry,
        exc: IngestionError,
        started_at: datetime,
        requested_url: str,
        run_type: str,
    ) -> IngestionOutcome:
        completed = _now()
        status = (
            IngestionRunStatus.BLOCKED.value
            if exc.error_code
            in {
                "domain_not_allowed",
                "redirect_violation",
                "requires_browser",
                "requires_authentication",
                "configuration_error",
            }
            else IngestionRunStatus.FAILED.value
        )
        outcome = IngestionOutcome(
            source_id=entry.source_id,
            status=status,
            requested_url=requested_url,
            duration_ms=_duration_ms(started_at, completed),
            error_code=exc.error_code,
            error_message=str(exc),
        )
        self._record_run(session, entry, outcome, started_at, completed, run_type)
        return outcome
