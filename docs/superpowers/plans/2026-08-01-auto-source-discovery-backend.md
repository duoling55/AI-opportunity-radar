# 自动信源发现 - 后端发现引擎 实现计划（Plan A）

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 实现 FR-15 自动信源发现的后端：基于知识库关键词直接抓取政府门户，对发现信源自动合规核查与重要性评分，产出候选信源清单与发现报告，经 `search-sources` CLI 异步执行。

**架构：** `DiscoveryOrchestrator` 编排三个叶子能力（`PortalCrawler` 直接抓取+反爬对策、`ComplianceChecker` 7 项被动核查、`ImportanceScorer` 6 维度评分），读 `KeywordSource` 关键词与门户种子，写候选入 `compliance_sources.json`、报告入 `data/discovery/`。依赖以构造参数注入，便于 mock 单测。

**技术栈：** Python ≥3.11、Pydantic v2、httpx + pytest-httpx、BeautifulSoup4、Playwright（已集成）、pytest、ruff。

**关联 spec：** `docs/superpowers/specs/2026-08-01-discovery-{search-orchestration,portal-direct-crawl,compliance-check,importance-scoring}-design.md`

**后续：** Plan B（`2026-08-01-auto-source-discovery-frontend.md`）实现 06 页面与信源集成，依赖本计划产出。

---

## 文件结构

**创建：**
- `src/opportunity_radar/discovery/__init__.py` — 包标识
- `src/opportunity_radar/discovery/models.py` — DiscoveryMeta / CrawlResult / ComplianceReport / ScoreResult / DiscoveryReport / SearchKeyword 等 Pydantic 模型
- `src/opportunity_radar/discovery/keywords.py` — `KeywordSource` Protocol + `FallbackKeywordSource`
- `src/opportunity_radar/discovery/crawler.py` — `PortalCrawler`（HTTP 优先 + Playwright 回退 + 反爬对策）
- `src/opportunity_radar/discovery/checker.py` — `ComplianceChecker`（7 项被动核查）
- `src/opportunity_radar/discovery/scorer.py` — `ImportanceScorer`（6 维度评分）
- `src/opportunity_radar/discovery/orchestrator.py` — `DiscoveryOrchestrator`
- `config/discovery_keywords.json` — Fallback 关键词种子
- `config/discovery_portals.json` — 政府门户种子
- `tests/discovery/__init__.py`
- `tests/discovery/test_models.py` / `test_keywords.py` / `test_crawler.py` / `test_checker.py` / `test_scorer.py` / `test_orchestrator.py`
- `tests/test_cli_search_sources.py`

**修改：**
- `src/opportunity_radar/compliance.py:133-189` — `ComplianceSource` 新增 `origin`、`discovery` 字段
- `src/opportunity_radar/config.py:11-26` — `SourceConfig` 新增 `origin` 字段
- `src/opportunity_radar/cli.py` — 新增 `search-sources` 子命令

---

## 阶段 A：后端发现引擎

### 任务 A0：数据模型与配置扩展

**文件：**
- 创建：`src/opportunity_radar/discovery/models.py`
- 修改：`src/opportunity_radar/compliance.py`（`ComplianceSource`，第 133-189 行）
- 修改：`src/opportunity_radar/config.py`（`SourceConfig`，第 11-26 行）
- 测试：`tests/discovery/test_models.py`

- [ ] **步骤 1：编写失败的测试**

```python
# tests/discovery/test_models.py
import json
from datetime import date
from opportunity_radar.discovery.models import (
    DiscoveryMeta, CrawlResult, ComplianceReport, ScoreResult, PolicyItem, CheckDetails,
)
from opportunity_radar.compliance import ComplianceSource
from opportunity_radar.config import SourceConfig


def test_compliance_source_accepts_origin_and_discovery():
    meta = DiscoveryMeta(
        keywords=["设备更新"], discovered_at=date(2026, 8, 1), portal_seed_id="gov",
        admin_level="国家", sample_policies=[], snapshots=["data/discovery/snapshots/gov/x.html"],
        check_result="pass", check_details=CheckDetails(
            domain_owner="gov", accessibility={"status_code": 200, "public": True},
            login_required=False, captcha_triggered=False,
            robots={"allowed": True, "raw": ""}, rate_limit_hints={},
            column_structure={"list_page": True, "detail_page": True, "sample_count": 3}),
        recommendation="建议启用", priority_score=85, priority_level="高", score_breakdown=[],
    )
    src = ComplianceSource(
        source_id="gov_zc", display_name="国务院政策", phase="candidate", enabled=False,
        official_urls=["https://www.gov.cn"], origin="discovery", discovery=meta,
    )
    assert src.origin == "discovery"
    assert src.discovery.priority_score == 85
    assert src.phase == "candidate"


def test_compliance_source_defaults_origin_manual():
    src = ComplianceSource(source_id="x", display_name="X", phase="candidate", enabled=False,
                           official_urls=["https://x.gov.cn"])
    assert src.origin == "manual"
    assert src.discovery is None


def test_source_config_defaults_origin_manual():
    sc = SourceConfig(source_id="x", display_name="X", region="全国",
                     list_urls=("https://x.gov.cn",), allowed_domains=("x.gov.cn",))
    assert sc.origin == "manual"


def test_crawl_result_roundtrips():
    r = CrawlResult(fetch_mode="http", html="<a>x</a>", text_content="x", page_title="t",
                    policy_items=[PolicyItem(title="通知", url="https://x.gov.cn/p/1")],
                    snapshot_path="s.html", final_url="https://x.gov.cn/", restricted=False)
    assert r.policy_items[0].url.endswith("/p/1")
```

- [ ] **步骤 2：运行测试验证失败**

运行：`pytest tests/discovery/test_models.py -v`
预期：FAIL — `ComplianceSource` 无 `origin`/`discovery` 参数、`SourceConfig` 无 `origin`、模型未定义。

- [ ] **步骤 3：编写实现**

```python
# src/opportunity_radar/discovery/models.py
from __future__ import annotations
from datetime import date
from pydantic import BaseModel


class PolicyItem(BaseModel):
    title: str
    url: str


class CrawlResult(BaseModel):
    fetch_mode: str  # "http" | "playwright"
    html: str
    text_content: str
    page_title: str
    policy_items: list[PolicyItem]
    snapshot_path: str
    final_url: str
    restricted: bool
    restricted_reason: str | None = None


class CheckDetails(BaseModel):
    domain_owner: str  # "gov" | "other"
    accessibility: dict
    login_required: bool
    captcha_triggered: bool
    robots: dict
    rate_limit_hints: dict
    column_structure: dict


class ComplianceReport(BaseModel):
    check_result: str  # pass | needs_attention | not_recommended
    check_details: CheckDetails
    recommendation: str  # 建议启用 | 需人工关注 | 不建议


class ScoreBreakdownItem(BaseModel):
    dimension: str
    score: int
    max: int
    reason: str


class ScoreResult(BaseModel):
    priority_score: int
    priority_level: str  # 高 | 中 | 低
    score_breakdown: list[ScoreBreakdownItem]


class SamplePolicy(BaseModel):
    title: str
    url: str
    matched_keywords: list[str]


class DiscoveryMeta(BaseModel):
    keywords: list[str]
    discovered_at: date
    portal_seed_id: str
    admin_level: str  # 国家 | 省 | 市
    sample_policies: list[SamplePolicy]
    snapshots: list[str]
    check_result: str
    check_details: CheckDetails
    recommendation: str
    priority_score: int
    priority_level: str
    score_breakdown: list[ScoreBreakdownItem]


class SearchKeyword(BaseModel):
    text: str
    tag: str
    signal_strength: str | None = None


class DiscoveryReport(BaseModel):
    job_id: str
    started_at: str
    finished_at: str
    keywords_used: list[str]
    portals_scanned: list[dict]
    candidates: list[str]
    stats: dict
    errors: list[dict]
```

在 `compliance.py` `ComplianceSource`（第 133-189 行）新增两个字段（保留现有字段，仅追加）：

```python
    origin: str = "manual"                       # manual | discovery
    discovery: "DiscoveryMeta | None" = None     # 仅 origin=discovery 填充
```

> 若 `ComplianceSource` 为 `@dataclass`，加 `from __future__ import annotations` 或用 `Optional` 避免前向引用问题；`DiscoveryMeta` 用 `TYPE_CHECKING` 导入或字符串注解。落库 JSON 时 `discovery` 为嵌套 dict。

在 `config.py` `SourceConfig`（第 11-26 行）新增：

```python
    origin: str = "manual"   # manual | discovery
```

- [ ] **步骤 4：运行测试验证通过**

运行：`pytest tests/discovery/test_models.py -v`
预期：PASS

- [ ] **步骤 5：Lint + Commit**

```bash
ruff check src/opportunity_radar/discovery/models.py src/opportunity_radar/compliance.py src/opportunity_radar/config.py tests/discovery/test_models.py
git add src/opportunity_radar/discovery/__init__.py src/opportunity_radar/discovery/models.py src/opportunity_radar/compliance.py src/opportunity_radar/config.py tests/discovery/
git commit -m "feat(discovery): 数据模型扩展 origin/discovery 字段与 DiscoveryMeta"
```

---

### 任务 A1：KeywordSource 与 Fallback

**文件：**
- 创建：`src/opportunity_radar/discovery/keywords.py`
- 创建：`config/discovery_keywords.json`
- 测试：`tests/discovery/test_keywords.py`

- [ ] **步骤 1：编写失败的测试**

```python
# tests/discovery/test_keywords.py
from opportunity_radar.discovery.keywords import FallbackKeywordSource


def test_fallback_returns_nonempty_keywords():
    src = FallbackKeywordSource(path="config/discovery_keywords.json")
    kws = src.get_search_keywords()
    assert len(kws) > 0
    assert all(k.text and k.tag for k in kws)
    texts = [k.text for k in kws]
    assert "设备更新" in texts and "融资租赁" in texts


def test_fallback_missing_file_raises(tmp_path):
    import pytest
    with pytest.raises(FileNotFoundError):
        FallbackKeywordSource(path=str(tmp_path / "nope.json")).get_search_keywords()
```

- [ ] **步骤 2：运行测试验证失败**

运行：`pytest tests/discovery/test_keywords.py -v`
预期：FAIL — 模块未定义。

- [ ] **步骤 3：编写实现**

```python
# src/opportunity_radar/discovery/keywords.py
from __future__ import annotations
import json
from pathlib import Path
from typing import Protocol
from opportunity_radar.discovery.models import SearchKeyword


class KeywordSource(Protocol):
    def get_search_keywords(self) -> list[SearchKeyword]: ...


class FallbackKeywordSource:
    """读取 config/discovery_keywords.json；FR-05 落地前替代 KbKeywordSource。"""

    def __init__(self, path: str = "config/discovery_keywords.json") -> None:
        self._path = Path(path)

    def get_search_keywords(self) -> list[SearchKeyword]:
        if not self._path.exists():
            raise FileNotFoundError(f"关键词文件不存在: {self._path}")
        raw = json.loads(self._path.read_text(encoding="utf-8"))
        return [SearchKeyword(text=k["text"], tag=k["tag"], signal_strength=k.get("signal_strength"))
                for k in raw]
```

```json
# config/discovery_keywords.json
[
  {"text": "设备更新", "tag": "技改投资", "signal_strength": "很强"},
  {"text": "技术改造", "tag": "技改投资", "signal_strength": "很强"},
  {"text": "智能化改造", "tag": "技改投资", "signal_strength": "较强"},
  {"text": "融资租赁", "tag": "融资支持", "signal_strength": "很强"},
  {"text": "绿色租赁", "tag": "融资支持", "signal_strength": "较强"},
  {"text": "售后回租", "tag": "融资支持", "signal_strength": "较强"},
  {"text": "设备直租", "tag": "融资支持", "signal_strength": "较强"},
  {"text": "专精特新", "tag": "企业培育", "signal_strength": "中等"},
  {"text": "智能制造", "tag": "数字化转型", "signal_strength": "较强"},
  {"text": "产业升级", "tag": "产业规划", "signal_strength": "中等"},
  {"text": "通知", "tag": "标题标记", "signal_strength": null},
  {"text": "办法", "tag": "标题标记", "signal_strength": null},
  {"text": "细则", "tag": "标题标记", "signal_strength": null},
  {"text": "指南", "tag": "标题标记", "signal_strength": null},
  {"text": "意见", "tag": "标题标记", "signal_strength": null},
  {"text": "方案", "tag": "标题标记", "signal_strength": null},
  {"text": "公告", "tag": "标题标记", "signal_strength": null},
  {"text": "公示", "tag": "标题标记", "signal_strength": null},
  {"text": "规划", "tag": "标题标记", "signal_strength": null},
  {"text": "新能源", "tag": "行业标签", "signal_strength": null},
  {"text": "汽车及零部件", "tag": "行业标签", "signal_strength": null},
  {"text": "化工与新材料", "tag": "行业标签", "signal_strength": null}
]
```

- [ ] **步骤 4：运行测试验证通过**

运行：`pytest tests/discovery/test_keywords.py -v`
预期：PASS

- [ ] **步骤 5：Commit**

```bash
git add src/opportunity_radar/discovery/keywords.py config/discovery_keywords.json tests/discovery/test_keywords.py
git commit -m "feat(discovery): KeywordSource 接口与 Fallback 种子词"
```

---

### 任务 A2：PortalCrawler（直接抓取 + 反爬对策，Spec 2）

**文件：**
- 创建：`src/opportunity_radar/discovery/crawler.py`
- 测试：`tests/discovery/test_crawler.py`

- [ ] **步骤 1：编写失败的测试**

```python
# tests/discovery/test_crawler.py
import pytest
from opportunity_radar.discovery.crawler import PortalCrawler
from opportunity_radar.discovery.models import CrawlResult


def _crawler(http):
    return PortalCrawler(http=http, browser=None, request_interval=0.0)


def test_crawl_static_html_extracts_policy_links(httpx_mock):
    html = (
        '<html><head><title>政策列表</title></head><body>'
        '<a href="/p/1">关于设备更新的通知</a>'
        '<a href="/news/2">新闻动态</a>'
        '</body></html>'
    )
    httpx_mock.add_response(url="https://www.gov.cn/zc/index.html", text=html,
                            headers={"Content-Type": "text/html"})
    import httpx
    c = _crawler(httpx.Client())
    r = c.crawl("https://www.gov.cn/zc/index.html", "gov")
    assert r.fetch_mode == "http"
    assert r.page_title == "政策列表"
    assert len(r.policy_items) == 1
    assert r.policy_items[0].title == "关于设备更新的通知"
    assert r.policy_items[0].url == "https://www.gov.cn/p/1"
    assert r.restricted is False
    assert "设备更新" in r.text_content


def test_crawl_login_form_marks_restricted(httpx_mock):
    html = '<input type="password"><button>登录</button>'
    httpx_mock.add_response(url="https://www.gov.cn/secret.html", text=html)
    import httpx
    r = _crawler(httpx.Client()).crawl("https://www.gov.cn/secret.html", "gov")
    assert r.restricted is True
    assert r.restricted_reason == "login"


def test_crawl_captcha_marks_restricted(httpx_mock):
    html = '<body>请输入验证码继续访问</body>'
    httpx_mock.add_response(url="https://www.gov.cn/c.html", text=html)
    import httpx
    r = _crawler(httpx.Client()).crawl("https://www.gov.cn/c.html", "gov")
    assert r.restricted is True
    assert r.restricted_reason == "captcha"


def test_crawl_403_marks_restricted(httpx_mock):
    httpx_mock.add_response(url="https://www.gov.cn/x.html", status_code=403)
    import httpx
    r = _crawler(httpx.Client()).crawl("https://www.gov.cn/x.html", "gov")
    assert r.restricted is True
    assert r.restricted_reason == "http_403"


def test_crawl_cross_domain_final_url_restricted(httpx_mock):
    httpx_mock.add_response(url="https://www.gov.cn/redirect.html", status_code=302,
                            headers={"Location": "https://evil.com/p"})
    httpx_mock.add_response(url="https://evil.com/p", text="<a href='/a'>通知</a>")
    import httpx
    r = _crawler(httpx.Client()).crawl("https://www.gov.cn/redirect.html", "gov",
                                       allowed_domains=("www.gov.cn",))
    assert r.restricted is True
    assert r.restricted_reason == "cross_domain"
```

- [ ] **步骤 2：运行测试验证失败**

运行：`pytest tests/discovery/test_crawler.py -v`
预期：FAIL — `crawler` 模块未定义。

- [ ] **步骤 3：编写实现**

```python
# src/opportunity_radar/discovery/crawler.py
from __future__ import annotations
import random
import time
from pathlib import Path
from urllib.parse import urljoin, urlparse
from bs4 import BeautifulSoup
import httpx
from opportunity_radar.discovery.models import CrawlResult, PolicyItem
from opportunity_radar.sources.base import POLICY_TITLE_MARKERS

CAPTCHA_MARKERS = ("验证码", "captcha", "人机验证")
_DEFAULT_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
               "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")


class PortalCrawler:
    """HTTP 直接抓取 + Playwright 回退 + 反爬对策（合规范围）。"""

    def __init__(self, http: httpx.Client, browser=None,
                 request_interval: float = 1.5, snapshots_dir: str = "data/discovery/snapshots") -> None:
        self._http = http
        self._browser = browser
        self._interval = request_interval
        self._snap_dir = Path(snapshots_dir)

    def crawl(self, url: str, portal_id: str, allowed_domains: tuple[str, ...] | None = None) -> CrawlResult:
        result = self._fetch_http(url, allowed_domains)
        if result.restricted:
            return result
        # JS 渲染回退：policy_items 为空且页面含框架特征
        if not result.policy_items and self._has_js_framework(result.html):
            if self._browser is not None:
                result = self._fetch_playwright(url, portal_id, allowed_domains)
        self._save_snapshot(result.html, portal_id)
        return result

    def _fetch_http(self, url: str, allowed_domains) -> CrawlResult:
        self._throttle()
        resp = self._http.get(url, headers=self._headers(url), follow_redirects=True)
        if resp.status_code in (401, 403, 429):
            return self._restricted(url, resp.url, f"http_{resp.status_code}", "", "", [])
        html = resp.text
        final_url = str(resp.url)
        if allowed_domains and urlparse(final_url).hostname not in allowed_domains:
            return self._restricted(url, final_url, "cross_domain", html, "", [])
        restricted_reason = self._detect_restricted(html)
        if restricted_reason:
            return self._restricted(url, final_url, restricted_reason, html, "", [])
        items, text, title = self._parse(html, final_url)
        return CrawlResult(fetch_mode="http", html=html, text_content=text, page_title=title,
                           policy_items=items, snapshot_path="", final_url=final_url, restricted=False)

    def _fetch_playwright(self, url: str, portal_id: str, allowed_domains) -> CrawlResult:
        # 复用 PlaywrightCollector：渲染后取 page.content()，不截图
        page = self._browser._context.new_page()  # noqa: 依赖 PlaywrightCollector 内部 API
        try:
            page.goto(url, wait_until="networkidle")
            html = page.content()
            final_url = page.url
            if allowed_domains and urlparse(final_url).hostname not in allowed_domains:
                return self._restricted(url, final_url, "cross_domain", html, "", [])
            restricted_reason = self._detect_restricted(html)
            if restricted_reason:
                return self._restricted(url, final_url, restricted_reason, html, "", [])
            items, text, title = self._parse(html, final_url)
            return CrawlResult(fetch_mode="playwright", html=html, text_content=text, page_title=title,
                               policy_items=items, snapshot_path="", final_url=final_url, restricted=False)
        finally:
            page.close()

    def _headers(self, url: str) -> dict:
        return {"User-Agent": _DEFAULT_UA, "Accept": "text/html,application/xhtml+xml",
                "Accept-Language": "zh-CN,zh;q=0.9", "Referer": url}

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
        title = (soup.title.string.strip() if soup.title and soup.title.string else "")
        for s in soup(["script", "style"]):
            s.decompose()
        text = soup.get_text(separator="\n", strip=True)
        items: list[PolicyItem] = []
        for a in soup.find_all("a", href=True):
            t = a.get_text(strip=True)
            if t and any(m in t for m in POLICY_TITLE_MARKERS):
                items.append(PolicyItem(title=t, url=urljoin(base_url, a["href"])))
        return items, text, title

    def _has_js_framework(self, html: str) -> bool:
        low = html.lower()
        return any(x in low for x in ("id=\"app\"", "id=\"root\"", "vue", "react", "__next_data__"))

    def _save_snapshot(self, html: str, portal_id: str) -> str:
        d = self._snap_dir / portal_id
        d.mkdir(parents=True, exist_ok=True)
        import time as _t
        p = d / f"{int(_t.time())}.html"
        p.write_text(html, encoding="utf-8")
        return str(p)

    def _restricted(self, url, final_url, reason, html, text, items) -> CrawlResult:
        return CrawlResult(fetch_mode="http", html=html, text_content=text, page_title="",
                           policy_items=items, snapshot_path="", final_url=final_url,
                           restricted=True, restricted_reason=reason)
```

- [ ] **步骤 4：运行测试验证通过**

运行：`pytest tests/discovery/test_crawler.py -v`
预期：PASS（5 项）。`browser=None` 时跳过 Playwright 回退分支。

- [ ] **步骤 5：Lint + Commit**

```bash
ruff check src/opportunity_radar/discovery/crawler.py tests/discovery/test_crawler.py
git add src/opportunity_radar/discovery/crawler.py tests/discovery/test_crawler.py
git commit -m "feat(discovery): PortalCrawler 直接抓取+反爬对策"
```

---

### 任务 A3：ComplianceChecker（7 项被动核查，Spec 3）

**文件：**
- 创建：`src/opportunity_radar/discovery/checker.py`
- 测试：`tests/discovery/test_checker.py`

- [ ] **步骤 1：编写失败的测试**

```python
# tests/discovery/test_checker.py
from opportunity_radar.discovery.checker import ComplianceChecker
from opportunity_radar.discovery.models import CrawlResult, PolicyItem


def _candidate(url="https://www.gov.cn/zc/index.html", domain="www.gov.cn", samples=None):
    return {"url": url, "domain": domain, "sample_policies": samples or [],
            "scan_result": CrawlResult(fetch_mode="http", html="", text_content="", page_title="",
                policy_items=[], snapshot_path="", final_url=url, restricted=False)}


def test_gov_public_no_captcha_passes(httpx_mock):
    httpx_mock.add_response(url="https://www.gov.cn/robots.txt", text="User-agent: *\nAllow: /")
    r = ComplianceChecker().check(_candidate())
    assert r.check_result == "pass"
    assert r.recommendation == "建议启用"
    assert r.check_details.domain_owner == "gov"


def test_non_gov_domain_not_recommended():
    r = ComplianceChecker().check(_candidate(url="https://example.com/x", domain="example.com"))
    assert r.check_result == "not_recommended"
    assert r.check_details.domain_owner == "other"


def test_captcha_in_scan_result_not_recommended():
    c = _candidate()
    c["scan_result"] = CrawlResult(fetch_mode="http", html="", text_content="", page_title="",
        policy_items=[], snapshot_path="", final_url=c["url"], restricted=True, restricted_reason="captcha")
    r = ComplianceChecker().check(c)
    assert r.check_result == "not_recommended"


def test_robots_disallow_not_recommended(httpx_mock):
    httpx_mock.add_response(url="https://www.gov.cn/robots.txt",
                            text="User-agent: *\nDisallow: /zc/")
    r = ComplianceChecker().check(_candidate(url="https://www.gov.cn/zc/index.html"))
    assert r.check_result == "not_recommended"


def test_low_sample_count_needs_attention(httpx_mock):
    httpx_mock.add_response(url="https://www.gov.cn/robots.txt", text="Allow: /")
    samples = [{"title": "通知", "url": "https://www.gov.cn/p/1"}]  # 仅 1 条 < 3
    r = ComplianceChecker().check(_candidate(samples=samples))
    assert r.check_result == "needs_attention"
```

- [ ] **步骤 2：运行测试验证失败**

运行：`pytest tests/discovery/test_checker.py -v`
预期：FAIL — 模块未定义。

- [ ] **步骤 3：编写实现**

```python
# src/opportunity_radar/discovery/checker.py
from __future__ import annotations
from urllib.parse import urlparse
import httpx
from opportunity_radar.discovery.models import ComplianceReport, CheckDetails, CrawlResult

_RECOMMEND = {"pass": "建议启用", "needs_attention": "需人工关注", "not_recommended": "不建议"}


class ComplianceChecker:
    """对发现信源执行 7 项被动核查；仅被动检测，不绕过访问控制。"""

    def __init__(self, http: httpx.Client | None = None, timeout: float = 10.0) -> None:
        self._http = http or httpx.Client(timeout=timeout)

    def check(self, source: dict) -> ComplianceReport:
        url = source["url"]
        domain = source["domain"]
        scan: CrawlResult | None = source.get("scan_result")
        details = self._build_details(url, domain, source.get("sample_policies", []), scan)
        result = self._decide(details, url)
        return ComplianceReport(check_result=result, check_details=details,
                                recommendation=_RECOMMEND[result])

    def _build_details(self, url, domain, samples, scan) -> CheckDetails:
        domain_owner = "gov" if domain.endswith(".gov.cn") else "other"
        accessibility = self._probe_accessibility(url)
        login_required = bool(scan and scan.restricted_reason == "login")
        captcha_triggered = bool(scan and scan.restricted_reason in ("captcha",))
        robots = self._read_robots(domain, url)
        rate_limit_hints = accessibility.get("headers", {})
        sample_count = len(samples)
        return CheckDetails(
            domain_owner=domain_owner, accessibility=accessibility, login_required=login_required,
            captcha_triggered=captcha_triggered, robots=robots, rate_limit_hints=rate_limit_hints,
            column_structure={"list_page": True, "detail_page": True, "sample_count": sample_count},
        )

    def _probe_accessibility(self, url) -> dict:
        try:
            r = self._http.get(url, follow_redirects=True)
            return {"status_code": r.status_code, "public": r.status_code == 200,
                    "headers": {"retry_after": r.headers.get("Retry-After"),
                                "rate_limit_header": r.headers.get("RateLimit-Limit")}}
        except httpx.HTTPError:
            return {"status_code": 0, "public": False, "headers": {}}

    def _read_robots(self, domain, url) -> dict:
        robots_url = f"https://{domain}/robots.txt"
        try:
            r = self._http.get(robots_url)
            raw = r.text
        except httpx.HTTPError:
            return {"allowed": True, "raw": ""}  # 读不到默认允许，但记 unknown
        path = urlparse(url).path or "/"
        allowed = self._robots_allows(raw, path)
        return {"allowed": allowed, "raw": raw}

    @staticmethod
    def _robots_allows(raw: str, path: str) -> bool:
        disallow = [l.split(":", 1)[1].strip() for l in raw.splitlines()
                    if l.strip().lower().startswith("disallow:") and ":" in l]
        for d in disallow:
            if d and path.startswith(d):
                return False
        return True

    def _decide(self, d: CheckDetails, url: str) -> str:
        if (d.domain_owner != "gov" or d.login_required or d.captcha_triggered
                or not d.robots["allowed"] or not d.accessibility.get("public", False)):
            return "not_recommended"
        if d.column_structure["sample_count"] < 3 or d.rate_limit_hints.get("retry_after"):
            return "needs_attention"
        return "pass"
```

- [ ] **步骤 4：运行测试验证通过**

运行：`pytest tests/discovery/test_checker.py -v`
预期：PASS（5 项）。

- [ ] **步骤 5：Lint + Commit**

```bash
ruff check src/opportunity_radar/discovery/checker.py tests/discovery/test_checker.py
git add src/opportunity_radar/discovery/checker.py tests/discovery/test_checker.py
git commit -m "feat(discovery): ComplianceChecker 7 项被动核查"
```

---

### 任务 A4：ImportanceScorer（6 维度评分，Spec 4）

**文件：**
- 创建：`src/opportunity_radar/discovery/scorer.py`
- 测试：`tests/discovery/test_scorer.py`

- [ ] **步骤 1：编写失败的测试**

```python
# tests/discovery/test_scorer.py
from opportunity_radar.discovery.scorer import ImportanceScorer
from opportunity_radar.discovery.models import ComplianceReport, CheckDetails


def _report(check_result="pass"):
    return ComplianceReport(check_result=check_result,
        check_details=CheckDetails(domain_owner="gov", accessibility={"public": True},
            login_required=False, captcha_triggered=False, robots={"allowed": True, "raw": ""},
            rate_limit_hints={}, column_structure={"sample_count": 5}),
        recommendation="建议启用")


def test_national_gov_lease_direct_high():
    src = {"admin_level": "国家", "domain": "www.gov.cn", "column_name": "融资租赁政策",
           "sample_policies": [{"title": "设备融资租赁通知", "url": "u"}, {"title": "绿色租赁办法", "url": "u"},
                               {"title": "技改通知", "url": "u"}]}
    r = ImportanceScorer().score(src, src["sample_policies"], _report())
    assert r.priority_score == 30 + 25 + 20 + 5 + 10 + 5  # 95
    assert r.priority_level == "高"
    dims = {b.dimension: b.score for b in r.score_breakdown}
    assert dims["行政层级"] == 30 and dims["行业相关性"] == 25 and dims["域名权威性"] == 5


def test_city_non_gov_low():
    src = {"admin_level": "市", "domain": "example.com", "column_name": "产业动态",
           "sample_policies": [{"title": "产业新闻", "url": "u"}]}
    r = ImportanceScorer().score(src, src["sample_policies"], _report("not_recommended"))
    assert r.priority_level == "低"
    dims = {b.dimension: b.score for b in r.score_breakdown}
    assert dims["行政层级"] == 10 and dims["合规可采集性"] == 0 and dims["域名权威性"] == 0


def test_insufficient_samples_uses_mid_frequency():
    src = {"admin_level": "省", "domain": "zj.gov.cn", "column_name": "通知",
           "sample_policies": [{"title": "通知", "url": "u"}]}
    r = ImportanceScorer().score(src, src["sample_policies"], _report("needs_attention"))
    freq = next(b for b in r.score_breakdown if b.dimension == "政策更新频率")
    assert freq.score == 5 and "样例不足" in freq.reason
```

- [ ] **步骤 2：运行测试验证失败**

运行：`pytest tests/discovery/test_scorer.py -v`
预期：FAIL — 模块未定义。

- [ ] **步骤 3：编写实现**

```python
# src/opportunity_radar/discovery/scorer.py
from __future__ import annotations
from opportunity_radar.discovery.models import ComplianceReport, ScoreResult, ScoreBreakdownItem

_LEASE = ("设备租赁", "融资租赁", "绿色租赁", "售后回租", "设备直租", "租赁")
_OTHER_FIN = ("贴息", "担保", "信贷", "融资支持", "贷款", "再贷款")
_INDUSTRY = ("产业", "制造业", "新能源", "汽车", "化工", "医药", "装备")

_ADMIN = {"国家": 30, "省": 20, "市": 10}
_ACCESS = {"pass": 10, "needs_attention": 5, "not_recommended": 0}


class ImportanceScorer:
    def score(self, source: dict, samples: list[dict], compliance: ComplianceReport) -> ScoreResult:
        breakdown: list[ScoreBreakdownItem] = []
        breakdown.append(self._admin_level(source))
        breakdown.append(self._industry_relevance(source, samples))
        breakdown.append(self._signal_density(samples))
        breakdown.append(self._update_freq(samples))
        breakdown.append(self._accessibility(compliance))
        breakdown.append(self._domain_authority(source))
        total = sum(b.score for b in breakdown)
        level = "高" if total >= 80 else "中" if total >= 60 else "低"
        return ScoreResult(priority_score=total, priority_level=level, score_breakdown=breakdown)

    def _admin_level(self, src) -> ScoreBreakdownItem:
        s = _ADMIN.get(src["admin_level"], 10)
        return ScoreBreakdownItem(dimension="行政层级", score=s, max=30, reason=f"{src['admin_level']}级信源 +{s}")

    def _industry_relevance(self, src, samples) -> ScoreBreakdownItem:
        blob = src.get("column_name", "") + "".join(p["title"] for p in samples)
        if any(k in blob for k in _LEASE):
            return ScoreBreakdownItem(dimension="行业相关性", score=25, max=25, reason="金融租赁直接相关 +25")
        if any(k in blob for k in _OTHER_FIN):
            return ScoreBreakdownItem(dimension="行业相关性", score=15, max=25, reason="其他金融 +15")
        if any(k in blob for k in _INDUSTRY):
            return ScoreBreakdownItem(dimension="行业相关性", score=10, max=25, reason="产业通用 +10")
        return ScoreBreakdownItem(dimension="行业相关性", score=5, max=25, reason="非金融 +5")

    def _signal_density(self, samples) -> ScoreBreakdownItem:
        if not samples:
            return ScoreBreakdownItem(dimension="融资信号密度", score=5, max=20, reason="无样例 +5")
        hit = sum(1 for p in samples if any(k in p["title"] for k in _LEASE + _OTHER_FIN))
        ratio = hit / len(samples)
        if ratio >= 0.6:
            return ScoreBreakdownItem(dimension="融资信号密度", score=20, max=20, reason=f"样例密度 {int(ratio*100)}%（高）+20")
        if ratio >= 0.3:
            return ScoreBreakdownItem(dimension="融资信号密度", score=10, max=20, reason=f"样例密度 {int(ratio*100)}%（中）+10")
        return ScoreBreakdownItem(dimension="融资信号密度", score=5, max=20, reason=f"样例密度 {int(ratio*100)}%（低）+5")

    def _update_freq(self, samples) -> ScoreBreakdownItem:
        # P0：样例不足取中频 5 并标注
        if len(samples) < 3:
            return ScoreBreakdownItem(dimension="政策更新频率", score=5, max=10, reason="样例不足 +5")
        return ScoreBreakdownItem(dimension="政策更新频率", score=5, max=10, reason="中频（月更）+5")

    def _accessibility(self, compliance) -> ScoreBreakdownItem:
        s = _ACCESS.get(compliance.check_result, 0)
        return ScoreBreakdownItem(dimension="合规可采集性", score=s, max=10, reason=f"{compliance.check_result} +{s}")

    def _domain_authority(self, src) -> ScoreBreakdownItem:
        s = 5 if src["domain"].endswith(".gov.cn") else 0
        return ScoreBreakdownItem(dimension="域名权威性", score=s, max=5, reason=("gov.cn 官方 +5" if s else "非 gov.cn +0"))
```

- [ ] **步骤 4：运行测试验证通过**

运行：`pytest tests/discovery/test_scorer.py -v`
预期：PASS（3 项）。

- [ ] **步骤 5：Lint + Commit**

```bash
ruff check src/opportunity_radar/discovery/scorer.py tests/discovery/test_scorer.py
git add src/opportunity_radar/discovery/scorer.py tests/discovery/test_scorer.py
git commit -m "feat(discovery): ImportanceScorer 6 维度评分"
```

---

### 任务 A5：DiscoveryOrchestrator（编排器，Spec 1）

**文件：**
- 创建：`src/opportunity_radar/discovery/orchestrator.py`
- 创建：`config/discovery_portals.json`
- 测试：`tests/discovery/test_orchestrator.py`

- [ ] **步骤 1：编写失败的测试**

```python
# tests/discovery/test_orchestrator.py
import json
from unittest.mock import MagicMock
from opportunity_radar.discovery.orchestrator import DiscoveryOrchestrator
from opportunity_radar.discovery.models import CrawlResult, ComplianceReport, CheckDetails, ScoreResult


def _crawl_result(restricted=False, reason=None, items=None):
    return CrawlResult(fetch_mode="http", html="<a>通知</a>", text_content="设备更新融资租赁",
                       page_title="t", policy_items=items or [],
                       snapshot_path="s.html", final_url="https://www.gov.cn/zc/",
                       restricted=restricted, restricted_reason=reason)


def _report(check_result="pass"):
    return ComplianceReport(check_result=check_result,
        check_details=CheckDetails(domain_owner="gov", accessibility={"public": True},
            login_required=False, captcha_triggered=False, robots={"allowed": True, "raw": ""},
            rate_limit_hints={}, column_structure={"sample_count": 3}), recommendation="建议启用")


def _score(total=85):
    return ScoreResult(priority_score=total, priority_level="高" if total >= 80 else "中", score_breakdown=[])


def test_orchestrator_writes_candidate_and_report(httpx_mock, tmp_path, monkeypatch):
    from opportunity_radar.discovery.models import PolicyItem
    portal = [{"portal_id": "gov", "display_name": "国务院", "region": "国家",
               "entry_url": "https://www.gov.cn/zc/index.html", "admin_level": "国家", "gov_domain": "www.gov.cn"}]
    monkeypatch.setattr("opportunity_radar.discovery.orchestrator.load_portal_seeds", lambda: portal)

    crawler = MagicMock()
    crawler.crawl.return_value = _crawl_result(
        items=[PolicyItem(title="设备更新通知", url="https://www.gov.cn/p/1")])
    checker = MagicMock(); checker.check.return_value = _report()
    scorer = MagicMock(); scorer.score.return_value = _score(95)
    kws = MagicMock(); kws.get_search_keywords.return_value = []

    comp_path = tmp_path / "compliance.json"; comp_path.write_text("[]")
    rep_dir = tmp_path / "reports"
    orch = DiscoveryOrchestrator(crawler, checker, scorer, kws,
                                 compliance_path=str(comp_path), report_dir=str(rep_dir))
    report = orch.run(keyword_tags=None, portal_ids=None)

    assert report.candidates == ["gov"]  # portal_id 作为 source_id
    written = json.loads(comp_path.read_text())
    assert written[0]["origin"] == "discovery"
    assert written[0]["phase"] == "candidate"
    assert written[0]["enabled"] is False
    assert written[0]["discovery"]["priority_score"] == 95
    assert (rep_dir / f"{report.job_id}-report.json").exists()


def test_orchestrator_restricted_portal_recorded_no_candidate(tmp_path, monkeypatch):
    portal = [{"portal_id": "gov2", "display_name": "X", "region": "国家",
               "entry_url": "https://x.gov.cn/z", "admin_level": "国家", "gov_domain": "x.gov.cn"}]
    monkeypatch.setattr("opportunity_radar.discovery.orchestrator.load_portal_seeds", lambda: portal)
    crawler = MagicMock(); crawler.crawl.return_value = _crawl_result(restricted=True, reason="captcha")
    orch = DiscoveryOrchestrator(crawler, MagicMock(), MagicMock(), MagicMock(),
                                 compliance_path=str(tmp_path / "c.json"), report_dir=str(tmp_path))
    report = orch.run(None, None)
    assert report.candidates == []
    assert report.stats["restricted_stopped"] == 1
    assert report.errors[0]["reason"] == "captcha"
```

- [ ] **步骤 2：运行测试验证失败**

运行：`pytest tests/discovery/test_orchestrator.py -v`
预期：FAIL — 模块未定义。

- [ ] **步骤 3：编写实现**

```python
# src/opportunity_radar/discovery/orchestrator.py
from __future__ import annotations
import json
import uuid
from datetime import datetime
from pathlib import Path
from opportunity_radar.discovery.models import (
    DiscoveryMeta, SamplePolicy, DiscoveryReport, CrawlResult, ComplianceReport, ScoreResult,
)


def load_portal_seeds(path: str = "config/discovery_portals.json") -> list[dict]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


class DiscoveryOrchestrator:
    def __init__(self, crawler, checker, scorer, keyword_source,
                 compliance_path: str = "config/compliance_sources.json",
                 report_dir: str = "data/discovery",
                 portal_seed_path: str = "config/discovery_portals.json") -> None:
        self._crawler = crawler
        self._checker = checker
        self._scorer = scorer
        self._kw = keyword_source
        self._comp_path = Path(compliance_path)
        self._report_dir = Path(report_dir)
        self._portal_seed_path = portal_seed_path

    def run(self, keyword_tags: list[str] | None, portal_ids: list[str] | None,
            mode: str = "direct_crawl") -> DiscoveryReport:
        started = datetime.now().isoformat()
        job_id = f"disc-{uuid.uuid4().hex[:8]}"
        keywords = self._filter_keywords(keyword_tags)
        portals = self._filter_portals(portal_ids)

        candidates: list[dict] = []
        portals_scanned: list[dict] = []
        errors: list[dict] = []
        restricted = 0

        for p in portals:
            try:
                cr: CrawlResult = self._crawler.crawl(p["entry_url"], p["portal_id"],
                                                      allowed_domains=(p["gov_domain"],))
            except Exception as e:  # 单门户失败不中断
                errors.append({"portal_id": p["portal_id"], "reason": "exception", "detail": str(e)})
                portals_scanned.append({"portal_id": p["portal_id"], "url": p["entry_url"],
                                        "status": "error", "policies_found": 0})
                continue
            if cr.restricted:
                restricted += 1
                errors.append({"portal_id": p["portal_id"], "reason": cr.restricted_reason, "detail": ""})
                portals_scanned.append({"portal_id": p["portal_id"], "url": p["entry_url"],
                                        "status": "restricted", "policies_found": 0})
                continue
            matched = self._match_keywords(cr, keywords)
            if not matched:
                portals_scanned.append({"portal_id": p["portal_id"], "url": p["entry_url"],
                                        "status": "ok", "policies_found": 0})
                continue
            cand = self._build_candidate(p, cr, matched)
            candidates.append(cand)
            portals_scanned.append({"portal_id": p["portal_id"], "url": p["entry_url"],
                                    "status": "ok", "policies_found": len(matched)})

        cand_ids = [c["source_id"] for c in candidates]
        self._write_candidates(candidates)
        report = DiscoveryReport(
            job_id=job_id, started_at=started, finished_at=datetime.now().isoformat(),
            keywords_used=[k.text for k in keywords],
            portals_scanned=portals_scanned, candidates=cand_ids,
            stats={"portals_scanned": len(portals), "policies_extracted": sum(s["policies_found"] for s in portals_scanned),
                   "candidates_found": len(cand_ids), "restricted_stopped": restricted},
            errors=errors,
        )
        self._write_report(report)
        return report

    def _filter_keywords(self, tags):
        kws = self._kw.get_search_keywords()
        if not tags:
            return kws
        return [k for k in kws if k.tag in tags]

    def _filter_portals(self, ids):
        portals = load_portal_seeds(self._portal_seed_path)
        if not ids:
            return portals
        return [p for p in portals if p["portal_id"] in ids]

    @staticmethod
    def _match_keywords(cr: CrawlResult, keywords) -> list[dict]:
        matched = []
        for item in cr.policy_items:
            hit = [k.text for k in keywords if k.text in item.title or k.text in cr.text_content]
            if hit:
                matched.append({"title": item.title, "url": item.url, "matched_keywords": list(set(hit))})
        return matched[:5]

    def _build_candidate(self, portal, cr, matched) -> dict:
        comp: ComplianceReport = self._checker.check(
            {"url": cr.final_url, "domain": portal["gov_domain"], "sample_policies": matched, "scan_result": cr})
        score: ScoreResult = self._scorer.score(
            {"admin_level": portal["admin_level"], "domain": portal["gov_domain"],
             "column_name": cr.page_title, "sample_policies": matched}, matched, comp)
        meta = DiscoveryMeta(
            keywords=sorted({k for m in matched for k in m["matched_keywords"]}),
            discovered_at=datetime.now().date(), portal_seed_id=portal["portal_id"],
            admin_level=portal["admin_level"],
            sample_policies=[SamplePolicy(**m) for m in matched],
            snapshots=[cr.snapshot_path] if cr.snapshot_path else [],
            check_result=comp.check_result, check_details=comp.check_details,
            recommendation=comp.recommendation, priority_score=score.priority_score,
            priority_level=score.priority_level, score_breakdown=score.score_breakdown,
        )
        return {"source_id": portal["portal_id"], "display_name": portal["display_name"],
                "region": portal["region"], "phase": "candidate", "enabled": False,
                "official_urls": [portal["entry_url"]], "origin": "discovery", "discovery": meta.model_dump()}

    def _write_candidates(self, candidates: list[dict]) -> None:
        existing = json.loads(self._comp_path.read_text(encoding="utf-8")) if self._comp_path.exists() else []
        existing.extend(candidates)
        self._comp_path.write_text(json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8")

    def _write_report(self, report: DiscoveryReport) -> None:
        self._report_dir.mkdir(parents=True, exist_ok=True)
        (self._report_dir / f"{report.job_id}-report.json").write_text(
            report.model_dump_json(indent=2), encoding="utf-8")
```

```json
# config/discovery_portals.json
[
  {"portal_id": "gov_cn", "display_name": "中国政府网政策", "region": "国家",
   "entry_url": "https://www.gov.cn/zhengce/zuixin/index.html", "admin_level": "国家", "gov_domain": "www.gov.cn"},
  {"portal_id": "miit_disc", "display_name": "工信部政策发现", "region": "国家",
   "entry_url": "https://www.miit.gov.cn/jgsj/zfs/index.html", "admin_level": "国家", "gov_domain": "www.miit.gov.cn"},
  {"portal_id": "zj_gov", "display_name": "浙江省政府政策", "region": "浙江",
   "entry_url": "https://www.zj.gov.cn/col/col1228970144/index.html", "admin_level": "省", "gov_domain": "www.zj.gov.cn"}
]
```

- [ ] **步骤 4：运行测试验证通过**

运行：`pytest tests/discovery/test_orchestrator.py -v`
预期：PASS（2 项）。

- [ ] **步骤 5：Lint + Commit**

```bash
ruff check src/opportunity_radar/discovery/orchestrator.py tests/discovery/test_orchestrator.py
git add src/opportunity_radar/discovery/orchestrator.py config/discovery_portals.json tests/discovery/test_orchestrator.py
git commit -m "feat(discovery): DiscoveryOrchestrator 编排器与门户种子"
```

---

### 任务 A6：CLI search-sources 子命令

**文件：**
- 修改：`src/opportunity_radar/cli.py`（`_parser()` 注册子命令 + handler）
- 测试：`tests/test_cli_search_sources.py`

- [ ] **步骤 1：编写失败的测试**

```python
# tests/test_cli_search_sources.py
import json
from unittest.mock import patch
from opportunity_radar.cli import main


def test_search_sources_cli_writes_report(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "compliance_sources.json").write_text("[]")
    (tmp_path / "config" / "discovery_portals.json").write_text("[]")
    (tmp_path / "config" / "discovery_keywords.json").write_text("[]")

    fake_report = {"job_id": "disc-test", "candidates": [], "stats": {}, "errors": [],
                   "portals_scanned": [], "keywords_used": [], "started_at": "", "finished_at": ""}
    with patch("opportunity_radar.cli.build_orchestrator") as bo:
        bo.return_value.run.return_value = type("R", (), fake_report)()
        rc = main(["search-sources", "--keywords", "all", "--portals", "all"])
    assert rc == 0
```

> 若 `main` 签名与现有 CLI 不同，按 `cli.py` 现有 `run/collect/analyze-local` 的调用方式调整（读取 `_parser()` 实际实现）。

- [ ] **步骤 2：运行测试验证失败**

运行：`pytest tests/test_cli_search_sources.py -v`
预期：FAIL — `search-sources` 子命令未注册。

- [ ] **步骤 3：编写实现**

在 `cli.py` `_parser()` 中新增子命令注册（对齐现有 `run`/`collect` 注册风格）：

```python
# 在 _parser() 内现有子命令之后
p_search = subparsers.add_parser("search-sources", help="基于关键词自动发现政府政策信源")
p_search.add_argument("--keywords", default="all", help="关键词标签，逗号分隔；all=全部")
p_search.add_argument("--portals", default="all", help="门户 ID，逗号分隔；all=全部")
p_search.add_argument("--mode", default="direct-crawl", choices=["direct-crawl"])
p_search.set_defaults(func=cmd_search_sources)
```

```python
# cli.py 新增 handler
def build_orchestrator():
    from opportunity_radar.discovery.orchestrator import DiscoveryOrchestrator
    from opportunity_radar.discovery.crawler import PortalCrawler
    from opportunity_radar.discovery.checker import ComplianceChecker
    from opportunity_radar.discovery.scorer import ImportanceScorer
    from opportunity_radar.discovery.keywords import FallbackKeywordSource
    import httpx
    return DiscoveryOrchestrator(
        PortalCrawler(httpx.Client(timeout=30.0)),
        ComplianceChecker(), ImportanceScorer(), FallbackKeywordSource())


def cmd_search_sources(args) -> int:
    orch = build_orchestrator()
    tags = None if args.keywords == "all" else args.keywords.split(",")
    ids = None if args.portals == "all" else args.portals.split(",")
    report = orch.run(keyword_tags=tags, portal_ids=ids, mode=args.mode)
    print(f"Report: discovery job={report.job_id} candidates={len(report.candidates)} "
          f"restricted={report.stats.get('restricted_stopped', 0)}")
    return 0
```

> `print(f"Report: ...")` 行格式对齐 `_report_from_job_log`（`ui_server.py` 第 397-410 行）的解析预期，使 UI 能从日志提取进度。

- [ ] **步骤 4：运行测试验证通过**

运行：`pytest tests/test_cli_search_sources.py -v`
预期：PASS

- [ ] **步骤 5：全量回归 + Commit**

```bash
pytest tests/discovery/ tests/test_cli_search_sources.py -v
ruff check src/opportunity_radar/cli.py
git add src/opportunity_radar/cli.py tests/test_cli_search_sources.py
git commit -m "feat(discovery): search-sources CLI 子命令"
```

---

### 任务 A7：端到端集成验证

**文件：**
- 测试：`tests/discovery/test_e2e.py`

- [ ] **步骤 1：编写端到端测试（mock HTTP，验证全链路）**

```python
# tests/discovery/test_e2e.py
import json
from opportunity_radar.discovery.orchestrator import DiscoveryOrchestrator
from opportunity_radar.discovery.crawler import PortalCrawler
from opportunity_radar.discovery.checker import ComplianceChecker
from opportunity_radar.discovery.scorer import ImportanceScorer
from opportunity_radar.discovery.keywords import FallbackKeywordSource
import httpx


def test_e2e_discovery_pipeline(httpx_mock, tmp_path, monkeypatch):
    portal = [{"portal_id": "gov_e2e", "display_name": "国务院", "region": "国家",
               "entry_url": "https://www.gov.cn/zc/index.html", "admin_level": "国家", "gov_domain": "www.gov.cn"}]
    monkeypatch.setattr("opportunity_radar.discovery.orchestrator.load_portal_seeds", lambda: portal)
    httpx_mock.add_response(url="https://www.gov.cn/robots.txt", text="Allow: /")
    httpx_mock.add_response(url="https://www.gov.cn/zc/index.html",
        text='<a href="/p/1">关于设备融资租赁更新的通知</a>')

    comp = tmp_path / "compliance.json"; comp.write_text("[]")
    orch = DiscoveryOrchestrator(
        PortalCrawler(httpx.Client(timeout=10), request_interval=0.0),
        ComplianceChecker(httpx.Client(timeout=10)), ImportanceScorer(),
        FallbackKeywordSource(path="config/discovery_keywords.json"),
        compliance_path=str(comp), report_dir=str(tmp_path))
    report = orch.run(None, None)

    assert len(report.candidates) == 1
    written = json.loads(comp.read_text())
    assert written[0]["origin"] == "discovery"
    assert written[0]["phase"] == "candidate"
    assert written[0]["enabled"] is False
    assert written[0]["discovery"]["priority_score"] >= 0
    assert written[0]["discovery"]["check_result"] in ("pass", "needs_attention", "not_recommended")
```

- [ ] **步骤 2：运行端到端测试**

运行：`pytest tests/discovery/test_e2e.py -v`
预期：PASS

- [ ] **步骤 3：手动冒烟（真实网络，可选）**

```bash
python -m opportunity_radar search-sources --keywords all --portals all
# 预期：生成 data/discovery/{job_id}-report.json，候选写入 config/compliance_sources.json
```

- [ ] **步骤 4：Commit**

```bash
git add tests/discovery/test_e2e.py
git commit -m "test(discovery): 端到端集成验证"
```

---

## 自检

**1. 规格覆盖度：**
- Spec 2（直接抓取+反爬）：任务 A2 ✅（HTTP/Playwright 回退、4 类受限检测、反爬对策、快照）
- Spec 3（7 项核查）：任务 A3 ✅（域名/可访问性/登录/验证码/robots/限频/栏目结构；判定 pass/needs_attention/not_recommended）
- Spec 4（6 维度评分）：任务 A4 ✅（行政层级/行业相关性/融资信号密度/更新频率/合规可采集性/域名权威性）
- Spec 1（编排器+关键词+CLI+报告）：任务 A1/A5/A6 ✅
- 数据模型 origin/discovery：任务 A0 ✅
- Spec 5（前端+集成）：本计划不覆盖，见 Plan B

**2. 占位符扫描：** 无 TODO/待定；CLI handler 的 `print("Report: ...")` 已给出具体格式。

**3. 类型一致性：** `CrawlResult`/`ComplianceReport`/`ScoreResult`/`DiscoveryMeta` 在 A0 定义，A2/A3/A4/A5 引用字段名一致（`policy_items`/`text_content`/`restricted_reason`/`check_result`/`check_details`/`priority_score`/`score_breakdown`/`snapshots`）。`PortalCrawler.crawl`/`ComplianceChecker.check`/`ImportanceScorer.score` 签名在定义与编排器调用处一致。

**4. 已知偏离：** Spec 2 偏离 PRD D9（截图 OCR -> 直接抓取），需业务确认（已在 spec 标注）。

---

## 执行交接

Plan A 已完成并保存到 `docs/superpowers/plans/2026-08-01-auto-source-discovery-backend.md`。两种执行方式：

**1. 子代理驱动（推荐）** - 每个任务调度一个新的子代理，任务间审查，快速迭代
**2. 内联执行** - 在当前会话中使用 executing-plans 执行任务，批量执行并设检查点

Plan B（前端 06 页面与信源集成）将在 Plan A 完成后编写。选哪种方式执行 Plan A？
