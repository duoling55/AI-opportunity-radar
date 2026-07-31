from __future__ import annotations

import time
from datetime import date, datetime
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from opportunity_radar.models import PolicyCandidate, PolicyDocument
from opportunity_radar.normalization import content_hash, make_policy_id, normalize_text
from opportunity_radar.parsing.attachments import extract_attachment_text
from opportunity_radar.parsing.html import parse_html
from opportunity_radar.parsing.snapshot import save_snapshot
from opportunity_radar.sources.base import GenericHtmlSource, PolicySource

RESTRICTED_STATUSES = frozenset({401, 403, 429})
RESTRICTED_MARKERS = (
    "请输入验证码",
    "安全验证",
    "访问过于频繁",
    "captcha",
)
NEXT_PAGE_SELECTORS = (
    'a[title="下一页"]',
    "a.next",
    ".next a",
    'a:has-text("下一页")',
    'button:has-text("下一页")',
)
MAX_ATTACHMENT_BYTES = 30 * 1024 * 1024


def _allowed(url: str, allowed_domains: tuple[str, ...]) -> bool:
    return urlparse(url).hostname in allowed_domains


def _assert_allowed(url: str, allowed_domains: tuple[str, ...]) -> None:
    if not _allowed(url, allowed_domains):
        raise ValueError(f"URL is not allow-listed: {urlparse(url).hostname or '<missing>'}")


def _assert_unrestricted(status: int, body: str = "") -> None:
    if status in RESTRICTED_STATUSES:
        raise PermissionError(f"source access restricted: {status}")
    normalized = body.casefold()
    if any(marker.casefold() in normalized for marker in RESTRICTED_MARKERS):
        raise PermissionError("source access restricted: verification page")


class PlaywrightCollector:
    """Visible-browser collector for rendered official pages.

    It never handles login or CAPTCHA and stops a source on explicit access restriction.
    """

    def __init__(
        self,
        *,
        headless: bool = True,
        max_pages: int = 20,
        channel: str | None = None,
    ) -> None:
        if max_pages <= 0:
            raise ValueError("max_pages must be positive")
        self.headless = headless
        self.max_pages = max_pages
        self.channel = channel
        self._playwright: Any = None
        self._browser: Any = None
        self._context: Any = None
        self._page: Any = None

    def _ensure_started(self) -> None:
        if self._page is not None:
            return
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as error:
            raise RuntimeError(
                "browser collection requires: pip install -e .[browser]"
            ) from error
        self._playwright = sync_playwright().start()
        launch_options: dict[str, object] = {"headless": self.headless}
        if self.channel:
            launch_options["channel"] = self.channel
        self._browser = self._playwright.chromium.launch(**launch_options)
        self._context = self._browser.new_context(
            accept_downloads=True,
            user_agent="OpportunityRadar/0.1 (+policy research)",
        )
        self._page = self._context.new_page()

    def _navigate(
        self,
        url: str,
        source: GenericHtmlSource,
    ) -> str:
        self._ensure_started()
        _assert_allowed(url, source.config.allowed_domains)
        time.sleep(source.config.request_interval_seconds)
        response = self._page.goto(url, wait_until="domcontentloaded", timeout=30_000)
        status = response.status if response is not None else 200
        self._page.wait_for_timeout(750)
        rendered_url = self._page.url
        _assert_allowed(rendered_url, source.config.allowed_domains)
        html = self._page.content()
        _assert_unrestricted(status, html)
        return html

    def discover(
        self,
        source: PolicySource,
        start: date,
        end: date,
    ) -> list[PolicyCandidate]:
        if not isinstance(source, GenericHtmlSource):
            raise TypeError("browser collection requires GenericHtmlSource")
        found: dict[str, PolicyCandidate] = {}
        for list_url in source.config.list_urls:
            html = self._navigate(list_url, source)
            seen_pages: set[str] = set()
            for _ in range(self.max_pages):
                page_fingerprint = content_hash(self._page.url + html)
                if page_fingerprint in seen_pages:
                    break
                seen_pages.add(page_fingerprint)
                for candidate in source.discover_from_html(
                    self._page.url,
                    html,
                    start,
                    end,
                ):
                    found[str(candidate.detail_url)] = candidate
                if not self._go_to_next_page(source):
                    break
                html = self._page.content()
        return list(found.values())

    def _go_to_next_page(self, source: GenericHtmlSource) -> bool:
        for selector in NEXT_PAGE_SELECTORS:
            locator = self._page.locator(selector).first
            if locator.count() == 0 or not locator.is_visible():
                continue
            disabled = locator.get_attribute("disabled") is not None
            classes = (locator.get_attribute("class") or "").casefold()
            aria_disabled = (locator.get_attribute("aria-disabled") or "").casefold()
            if disabled or "disabled" in classes or aria_disabled == "true":
                return False
            previous_url = self._page.url
            previous_html = self._page.content()
            time.sleep(source.config.request_interval_seconds)
            locator.click(timeout=15_000)
            self._page.wait_for_timeout(1_000)
            _assert_allowed(self._page.url, source.config.allowed_domains)
            html = self._page.content()
            _assert_unrestricted(200, html)
            return self._page.url != previous_url or html != previous_html
        return False

    def fetch_document(
        self,
        source: PolicySource,
        candidate: PolicyCandidate,
        collected_at: datetime,
        raw_dir: Path,
    ) -> PolicyDocument:
        if not isinstance(source, GenericHtmlSource):
            raise TypeError("browser collection requires GenericHtmlSource")
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

        self._navigate(str(candidate.detail_url), source)
        try:
            self._page.wait_for_function(
                """selectors => selectors.some(selector => {
                    const node = document.querySelector(selector);
                    return node && (node.innerText || "").trim().length >= 20;
                })""",
                arg=list(source.detail_content_selectors),
                timeout=5_000,
            )
        except PlaywrightTimeoutError:
            self._page.wait_for_timeout(0)
        html = self._page.content()
        snapshot = save_snapshot(
            raw_dir,
            make_policy_id(candidate),
            "html",
            html.encode("utf-8"),
        )
        document = parse_html(
            candidate,
            source.config,
            html,
            collected_at,
            snapshot,
            source.detail_content_selectors,
        )
        text_parts = [document.normalized_text]
        snapshot_paths: list[str] = []
        errors: list[str] = []
        for index, attachment_url in enumerate(document.attachment_urls, start=1):
            url = str(attachment_url)
            filename = Path(unquote(urlparse(url).path)).name or f"attachment-{index}"
            suffix = Path(filename).suffix.lower().lstrip(".")
            if suffix == "doc":
                errors.append(f"旧版 Word .doc 附件不自动下载或解析（{filename}）")
                continue
            try:
                body, content_type = self._download(source, url)
                attachment_snapshot = save_snapshot(
                    raw_dir,
                    f"{document.policy_id}-attachment-{index}",
                    suffix or "bin",
                    body,
                )
                snapshot_paths.append(attachment_snapshot.as_posix())
                if not content_type or "octet-stream" in content_type.casefold():
                    content_type = {
                        "pdf": "application/pdf",
                        "docx": (
                            "application/vnd.openxmlformats-officedocument."
                            "wordprocessingml.document"
                        ),
                    }.get(suffix, content_type)
                attachment_text = extract_attachment_text(content_type, body)
                if not attachment_text:
                    raise ValueError("附件未提取到文本，可能需要 OCR 或人工复核")
                text_parts.append(f"[附件 {index}：{filename}]\n{attachment_text}")
            except PermissionError:
                raise
            except Exception as error:  # noqa: BLE001
                errors.append(f"附件解析失败（{filename}）：{type(error).__name__}: {error}")
        normalized_text = normalize_text("\n\n".join(text_parts))
        return document.model_copy(
            update={
                "normalized_text": normalized_text,
                "content_hash": content_hash(normalized_text),
                "attachment_snapshot_paths": snapshot_paths,
                "attachment_errors": errors,
            }
        )

    def _download(
        self,
        source: GenericHtmlSource,
        url: str,
    ) -> tuple[bytes, str]:
        self._ensure_started()
        _assert_allowed(url, source.config.allowed_domains)
        time.sleep(source.config.request_interval_seconds)
        response = self._context.request.get(url, timeout=30_000)
        _assert_allowed(response.url, source.config.allowed_domains)
        _assert_unrestricted(response.status)
        if not response.ok:
            raise RuntimeError(f"attachment request failed: {response.status}")
        declared_length = response.headers.get("content-length")
        if declared_length and int(declared_length) > MAX_ATTACHMENT_BYTES:
            raise ValueError("attachment exceeds 30 MiB limit")
        body = response.body()
        if len(body) > MAX_ATTACHMENT_BYTES:
            raise ValueError("attachment exceeds 30 MiB limit")
        return body, response.headers.get("content-type", "")

    def close(self) -> None:
        if self._context is not None:
            self._context.close()
        if self._browser is not None:
            self._browser.close()
        if self._playwright is not None:
            self._playwright.stop()
        self._page = None
        self._context = None
        self._browser = None
        self._playwright = None
