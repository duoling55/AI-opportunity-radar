from __future__ import annotations

import json
from datetime import date
from math import ceil
from urllib.parse import urlencode, urljoin

from bs4 import BeautifulSoup

from opportunity_radar.models import PolicyCandidate
from opportunity_radar.sources.base import GenericHtmlSource, _date_from_text

MAX_LIST_PAGES = 20


class MiitSource(GenericHtmlSource):
    listing_item_selectors = (".page-content li",)
    detail_content_selectors = (".ccontent", ".article", "article", "main")

    def discover(self, start: date, end: date) -> list[PolicyCandidate]:
        found: dict[str, PolicyCandidate] = {}
        for list_url in self.config.list_urls:
            landing_html = self.client.get(list_url).text
            landing = BeautifulSoup(landing_html, "html.parser")
            unit_script = landing.select_one("script[url][querydata]")
            if unit_script is None:
                candidates = self.discover_from_html(
                    list_url,
                    landing_html,
                    start,
                    end,
                )
                found.update(
                    (str(candidate.detail_url), candidate)
                    for candidate in candidates
                )
                continue

            endpoint = urljoin(list_url, str(unit_script["url"]))
            query = self._query_data(str(unit_script["querydata"]))
            page_number = 1
            page_size = 0
            while page_number <= MAX_LIST_PAGES:
                if page_number > 1:
                    query["paramJson"] = json.dumps(
                        {"pageNo": page_number, "pageSize": page_size},
                        ensure_ascii=False,
                        separators=(",", ":"),
                    )
                unit_html = self._unit_html(endpoint, query)
                candidates = self.discover_from_html(
                    list_url,
                    unit_html,
                    start,
                    end,
                )
                found.update(
                    (str(candidate.detail_url), candidate)
                    for candidate in candidates
                )

                unit = BeautifulSoup(unit_html, "html.parser")
                page_dates = [
                    published_at
                    for item in unit.select(".page-content li")
                    if (published_at := _date_from_text(item.get_text(" ", strip=True)))
                ]
                pagination = unit.select_one(".pagination")
                if pagination is None:
                    break
                page_size = int(pagination.get("rows", 0))
                total_count = int(pagination.get("count", 0))
                if page_size <= 0 or page_number >= ceil(total_count / page_size):
                    break
                if page_dates and min(page_dates) < start:
                    break
                page_number += 1
        return list(found.values())

    @staticmethod
    def _query_data(raw: str) -> dict[str, str]:
        payload = json.loads(raw.replace("'", '"'))
        if not isinstance(payload, dict):
            raise TypeError("MIIT unit queryData must be an object")
        return {str(key): str(value) for key, value in payload.items()}

    def _unit_html(self, endpoint: str, query: dict[str, str]) -> str:
        response = self.client.get(f"{endpoint}?{urlencode(query)}")
        payload = response.json()
        if not isinstance(payload, dict) or not isinstance(payload.get("data"), dict):
            raise TypeError("MIIT unit response is missing data")
        html = payload["data"].get("html")
        if not isinstance(html, str) or not html.strip():
            raise ValueError("MIIT unit response is missing data.html")
        return html
