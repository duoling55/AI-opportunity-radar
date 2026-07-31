from __future__ import annotations

import time
from urllib.parse import urlparse

import httpx

from opportunity_radar.config import SourceConfig


class OfficialHttpClient:
    def __init__(self, config: SourceConfig) -> None:
        self.config = config
        self.client = httpx.Client(
            timeout=20,
            follow_redirects=True,
            headers={"User-Agent": "OpportunityRadar/0.1 (+policy research)"},
            event_hooks={"request": [self._prepare_request]},
        )

    def _prepare_request(self, request: httpx.Request) -> None:
        hostname = request.url.host
        if hostname not in self.config.allowed_domains:
            raise ValueError(f"URL is not allow-listed: {hostname}")
        time.sleep(self.config.request_interval_seconds)

    def get(self, url: str) -> httpx.Response:
        hostname = urlparse(url).hostname or ""
        if hostname not in self.config.allowed_domains:
            raise ValueError(f"URL is not allow-listed: {hostname}")
        response = self.client.get(url)
        if response.status_code in {401, 403, 429}:
            raise PermissionError(f"source access restricted: {response.status_code}")
        response.raise_for_status()
        return response
