from __future__ import annotations

import random
import time
from pathlib import Path
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from opportunity_radar.discovery.models import CrawlResult, PolicyItem
from opportunity_radar.sources.base import POLICY_TITLE_MARKERS

CAPTCHA_MARKERS = ("验证码", "captcha", "人机验证")
_DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
_RESTRICTED_STATUSES = (401, 403, 429)


class PortalCrawler:
    """HTTP 直接抓取 + Playwright 回退 + 反爬对策（合规范围）。

    仅访问公开页面；遇验证码/登录/403/跨域即停止并标记受限，
    不绕过登录、不代理轮换、不伪造指纹。
    """

    def __init__(
        self,
        http: httpx.Client,
        browser=None,
        request_interval: float = 1.5,
        snapshots_dir: str = "data/discovery/snapshots",
    ) -> None:
        self._http = http
        self._browser = browser
        self._interval = request_interval
        self._snap_dir = Path(snapshots_dir)

    def crawl(
        self,
        url: str,
        portal_id: str,
        allowed_domains: tuple[str, ...] | None = None,
    ) -> CrawlResult:
        result = self._fetch_http(url, allowed_domains)
        if result.restricted:
            return result
        # JS 渲染回退：policy_items 为空且页面含框架特征且浏览器可用
        if (
            not result.policy_items
            and self._has_js_framework(result.html)
            and self._browser is not None
        ):
            result = self._fetch_playwright(url, allowed_domains)
        result.snapshot_path = self._save_snapshot(result.html, portal_id)
        return result

    def _fetch_http(self, url: str, allowed_domains) -> CrawlResult:
        self._throttle()
        resp = self._http.get(url, headers=self._headers(url), follow_redirects=True)
        if resp.status_code in _RESTRICTED_STATUSES:
            return self._restricted(
                str(resp.url), f"http_{resp.status_code}", "", "", []
            )
        html = resp.text
        final_url = str(resp.url)
        if allowed_domains and urlparse(final_url).hostname not in allowed_domains:
            return self._restricted(final_url, "cross_domain", html, "", [])
        restricted_reason = self._detect_restricted(html)
        if restricted_reason:
            return self._restricted(final_url, restricted_reason, html, "", [])
        items, text, title = self._parse(html, final_url)
        return CrawlResult(
            fetch_mode="http",
            html=html,
            text_content=text,
            page_title=title,
            policy_items=items,
            snapshot_path="",
            final_url=final_url,
            restricted=False,
        )

    def _fetch_playwright(self, url: str, allowed_domains) -> CrawlResult:
        # 复用 PlaywrightCollector 的浏览器上下文：渲染后取 page.content()，不截图。
        # NOTE: 依赖 PlaywrightCollector._context 内部 API（_ensure_started 后可用），
        # P0 单测 browser=None 不覆盖此分支；接入时按 browser.py 实际结构调整。
        self._throttle()
        self._browser._ensure_started()
        page = self._browser._context.new_page()
        try:
            page.goto(url, wait_until="networkidle")
            html = page.content()
            final_url = page.url
            if allowed_domains and urlparse(final_url).hostname not in allowed_domains:
                return self._restricted(final_url, "cross_domain", html, "", [], fetch_mode="playwright")
            restricted_reason = self._detect_restricted(html)
            if restricted_reason:
                return self._restricted(final_url, restricted_reason, html, "", [], fetch_mode="playwright")
            items, text, title = self._parse(html, final_url)
            return CrawlResult(
                fetch_mode="playwright",
                html=html,
                text_content=text,
                page_title=title,
                policy_items=items,
                snapshot_path="",
                final_url=final_url,
                restricted=False,
            )
        finally:
            page.close()

    def _headers(self, url: str) -> dict:
        return {
            "User-Agent": _DEFAULT_UA,
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "zh-CN,zh;q=0.9",
            "Referer": url,
        }

    def _throttle(self) -> None:
        if self._interval > 0:
            time.sleep(self._interval * (0.8 + 0.4 * random.random()))

    def _detect_restricted(self, html: str) -> str | None:
        low = html.lower()
        if "password" in low and ("登录" in html or "login" in low):
            return "login"
        if any(m in html or m.lower() in low for m in CAPTCHA_MARKERS):
            return "captcha"
        return None

    def _parse(self, html: str, base_url: str) -> tuple[list[PolicyItem], str, str]:
        soup = BeautifulSoup(html, "html.parser")
        title = soup.title.string.strip() if soup.title and soup.title.string else ""
        for tag in soup(["script", "style"]):
            tag.decompose()
        text = soup.get_text(separator="\n", strip=True)
        items: list[PolicyItem] = []
        for a in soup.find_all("a", href=True):
            link_text = a.get_text(strip=True)
            if link_text and any(m in link_text for m in POLICY_TITLE_MARKERS):
                items.append(PolicyItem(title=link_text, url=urljoin(base_url, a["href"])))
        return items, text, title

    def _has_js_framework(self, html: str) -> bool:
        low = html.lower()
        return any(
            x in low for x in ('id="app"', 'id="root"', "vue", "react", "__next_data__")
        )

    def _save_snapshot(self, html: str, portal_id: str) -> str:
        directory = self._snap_dir / portal_id
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{int(time.time())}.html"
        path.write_text(html, encoding="utf-8")
        return str(path)

    def _restricted(
        self, final_url: str, reason: str, html: str, text: str, items,
        fetch_mode: str = "http",
    ) -> CrawlResult:
        return CrawlResult(
            fetch_mode=fetch_mode,
            html=html,
            text_content=text,
            page_title="",
            policy_items=items,
            snapshot_path="",
            final_url=final_url,
            restricted=True,
            restricted_reason=reason,
        )
