import time
from dataclasses import dataclass, field
from urllib.parse import urlparse


@dataclass
class DomainRateLimiter:
    min_interval_seconds: float
    _last_request_by_domain: dict[str, float] = field(default_factory=dict)

    def wait(self, url: str) -> None:
        domain = urlparse(url).hostname or ""
        now = time.monotonic()
        last_request = self._last_request_by_domain.get(domain)
        if last_request is not None:
            remaining = self.min_interval_seconds - (now - last_request)
            if remaining > 0:
                time.sleep(remaining)
        self._last_request_by_domain[domain] = time.monotonic()
