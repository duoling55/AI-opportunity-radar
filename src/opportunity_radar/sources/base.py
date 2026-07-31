from __future__ import annotations

import re
from datetime import date
from typing import Protocol
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup
from bs4.element import Tag

from opportunity_radar.config import SourceConfig
from opportunity_radar.http import OfficialHttpClient
from opportunity_radar.models import PolicyCandidate

DATE = re.compile(r"(20\d{2})[-/.年](\d{1,2})[-/.月](\d{1,2})")
POLICY_TITLE_MARKERS = (
    "政策",
    "通知",
    "办法",
    "细则",
    "指南",
    "意见",
    "方案",
    "公告",
    "公示",
    "规划",
)


def _date_from_text(text: str) -> date | None:
    match = DATE.search(text)
    if not match:
        return None
    try:
        return date(*map(int, match.groups()))
    except ValueError:
        return None


def _listing_date(anchor: Tag) -> date | None:
    published_at = _date_from_text(anchor.get_text(" ", strip=True))
    if published_at:
        return published_at
    for siblings in (anchor.next_siblings, anchor.previous_siblings):
        for index, sibling in enumerate(siblings):
            if index >= 3:
                break
            if isinstance(sibling, Tag):
                if sibling.name == "a" or sibling.find("a"):
                    break
                text = sibling.get_text(" ", strip=True)
            else:
                text = str(sibling)
            published_at = _date_from_text(text)
            if published_at:
                return published_at
    parent = anchor.parent
    if (
        isinstance(parent, Tag)
        and parent.name not in {"body", "html"}
        and len(parent.select("a[href]")) == 1
    ):
        return _date_from_text(parent.get_text(" ", strip=True))
    return None


class PolicySource(Protocol):
    def discover(self, start: date, end: date) -> list[PolicyCandidate]: ...


class GenericHtmlSource:
    listing_item_selectors: tuple[str, ...] = ()
    detail_content_selectors: tuple[str, ...] = ("article", "main")

    def __init__(self, config: SourceConfig, client: OfficialHttpClient) -> None:
        self.config = config
        self.client = client

    def discover(self, start: date, end: date) -> list[PolicyCandidate]:
        found: dict[str, PolicyCandidate] = {}
        for list_url in self.config.list_urls:
            for candidate in self.discover_from_html(
                list_url,
                self.client.get(list_url).text,
                start,
                end,
            ):
                found[str(candidate.detail_url)] = candidate
        return list(found.values())

    def discover_from_html(
        self,
        list_url: str,
        html: str,
        start: date,
        end: date,
    ) -> list[PolicyCandidate]:
        """Discover candidates from already-rendered HTML."""
        soup = BeautifulSoup(html, "html.parser")
        found: dict[str, PolicyCandidate] = {}
        for anchor in self._listing_anchors(soup):
            href = anchor.get("href", "")
            title_attribute = anchor.get("title")
            title = (
                title_attribute.strip()
                if isinstance(title_attribute, str) and title_attribute.strip()
                else anchor.get_text(" ", strip=True)
            )
            if (
                not isinstance(href, str)
                or not href
                or len(title) < 4
                or not any(marker in title for marker in POLICY_TITLE_MARKERS)
            ):
                continue
            detail_url = urljoin(list_url, href)
            if urlparse(detail_url).hostname not in self.config.allowed_domains:
                continue
            published_at = _listing_date(anchor)
            if published_at and not start <= published_at <= end:
                continue
            candidate = PolicyCandidate(
                source_id=self.config.source_id,
                title=title,
                detail_url=detail_url,
                published_at=published_at,
            )
            found[str(candidate.detail_url)] = candidate
        return list(found.values())

    def _listing_anchors(self, soup: BeautifulSoup) -> list[Tag]:
        if not self.listing_item_selectors:
            return list(soup.select("a[href]"))
        anchors: list[Tag] = []
        for selector in self.listing_item_selectors:
            for item in soup.select(selector):
                if item.name == "a" and item.get("href"):
                    anchors.append(item)
                elif anchor := item.select_one("a[href]"):
                    anchors.append(anchor)
        return anchors
