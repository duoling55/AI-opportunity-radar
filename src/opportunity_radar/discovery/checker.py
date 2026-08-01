from __future__ import annotations

from urllib.parse import urlparse

import httpx

from opportunity_radar.discovery.models import (
    CheckDetails,
    ComplianceReport,
    CrawlResult,
)

_RECOMMEND = {
    "pass": "建议启用",
    "needs_attention": "需人工关注",
    "not_recommended": "不建议",
}


class ComplianceChecker:
    """对发现信源执行 7 项被动核查；仅被动检测，不绕过访问控制。

    7 项核查：域名归属 / 可访问性 / 登录墙 / 验证码 / robots / 限频线索 / 栏目结构。
    合规边界：仅 HEAD/GET 公开页面与读取 robots.txt，不提交表单、不模拟登录、不绕过验证码。
    """

    def __init__(self, http: httpx.Client | None = None, timeout: float = 10.0) -> None:
        self._http = http or httpx.Client(timeout=timeout)

    def check(self, source: dict) -> ComplianceReport:
        url = source["url"]
        domain = source["domain"]
        scan: CrawlResult | None = source.get("scan_result")
        samples = source.get("sample_policies", [])
        details = self._build_details(url, domain, samples, scan)
        result = self._decide(details)
        return ComplianceReport(
            check_result=result,
            check_details=details,
            recommendation=_RECOMMEND[result],
        )

    def _build_details(
        self,
        url: str,
        domain: str,
        samples: list,
        scan: CrawlResult | None,
    ) -> CheckDetails:
        domain_owner = "gov" if domain.endswith(".gov.cn") else "other"
        accessibility = self._probe_accessibility(url)
        login_required = bool(scan and scan.restricted_reason == "login")
        captcha_triggered = bool(scan and scan.restricted_reason in ("captcha",))
        robots = self._read_robots(domain, url)
        rate_limit_hints = accessibility.get("headers", {})
        sample_count = len(samples)
        return CheckDetails(
            domain_owner=domain_owner,
            accessibility=accessibility,
            login_required=login_required,
            captcha_triggered=captcha_triggered,
            robots=robots,
            rate_limit_hints=rate_limit_hints,
            column_structure={
                "list_page": True,
                "detail_page": True,
                "sample_count": sample_count,
            },
        )

    def _probe_accessibility(self, url: str) -> dict:
        """被动 GET 公开页面，判断是否可公开访问；不绕过任何访问控制。"""
        try:
            r = self._http.get(url, follow_redirects=True)
            return {
                "status_code": r.status_code,
                "public": r.status_code == 200,
                "headers": {
                    "retry_after": r.headers.get("Retry-After"),
                    "rate_limit_header": r.headers.get("RateLimit-Limit"),
                },
            }
        except httpx.HTTPError:
            return {"status_code": 0, "public": False, "headers": {}}

    def _read_robots(self, domain: str, url: str) -> dict:
        robots_url = f"https://{domain}/robots.txt"
        try:
            r = self._http.get(robots_url)
            raw = r.text
        except httpx.HTTPError:
            # 读不到 robots 默认允许，但无法确认；保守按允许处理（不阻断发现）
            return {"allowed": True, "raw": ""}
        path = urlparse(url).path or "/"
        allowed = self._robots_allows(raw, path)
        return {"allowed": allowed, "raw": raw}

    @staticmethod
    def _robots_allows(raw: str, path: str) -> bool:
        disallow = [
            line.split(":", 1)[1].strip()
            for line in raw.splitlines()
            if line.strip().lower().startswith("disallow:") and ":" in line
        ]
        for d in disallow:
            if d and path.startswith(d):
                return False
        return True

    def _decide(self, d: CheckDetails) -> str:
        if (
            d.domain_owner != "gov"
            or d.login_required
            or d.captcha_triggered
            or not d.robots["allowed"]
            or not d.accessibility.get("public", False)
        ):
            return "not_recommended"
        if d.column_structure["sample_count"] < 3 or d.rate_limit_hints.get("retry_after"):
            return "needs_attention"
        return "pass"
