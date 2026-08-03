# 自动信源发现 - 门户网页直接抓取与反爬对策设计

> 所属：FR-15 自动信源发现（P0 新增）
> 关联 spec：[[01 搜索任务执行]] · [[03 自动合规核查]] · [[04 重要性评分]] · [[05 06页面与信源交互]]
> 上游：FR-02 采集（PlaywrightCollector + OfficialHttpClient，复用其 HTTP 与浏览器能力）

## 1. 目的与范围

本 spec 是 FR-15 的**叶子能力模块**：对政府门户列表页进行直接网页抓取，提取政策标题、URL 与可见文本，供编排器做关键词匹配与候选生成；并内置面向公开页面的稳健抓取策略（反爬对策），保证在常见反爬场景下仍可获取公开内容。

**纳入**：HTTP 直接抓取 + HTML 解析、JS 渲染页面 Playwright 回退、反爬对策（真实请求头/限频抖动/退避重试/公开会话保持）、受限检测（验证码/登录/403/跨域）、HTML 快照保存。

**不纳入**：搜索编排（Spec 1）、合规核查判定（Spec 3）、评分（Spec 4）、前端展示（Spec 5）。本 spec 只产出 `CrawlResult` 供编排器消费。

**与 PRD 的差异（需业务确认）**：PRD D9 原定"政府门户访问 + 浏览器截图 + OCR"。本 spec 改为**直接抓取网页内容 + 反爬对策**，理由：① 直接解析 HTML/DOM 文本比 OCR 更准确、无识别误差；② 无需引入 OCR 依赖（RapidOCR/PaddlePaddle），Windows+macOS 部署更轻；③ 截图 OCR 本为规避动态渲染/反爬，改用 Playwright 渲染回退 + 稳健请求策略可达同等目的且更可靠。此偏离已记录，需业务确认更新 D9。

**合规边界（强制，对齐 NFR-04 与既有合规来源登记规则）**：反爬对策仅限"稳健抓取公开内容"，**绝不包括**登录/认证绕过、验证码破解、代理 IP 轮换规避封禁、浏览器指纹伪造。仅访问公开页面；遇验证码/登录即停止该门户并记录；遵守 robots.txt 与 Retry-After；不高频请求。

## 2. 功能描述

直接抓取政府门户政策栏目列表页 HTML，BeautifulSoup 解析政策链接与可见文本；对 JS 动态渲染页面回退 Playwright 渲染后解析 DOM（不截图）。内置反爬对策：真实浏览器请求头、请求间隔与随机抖动、429/503 指数退避重试、公开会话保持。遇验证码/登录/403/跨域跳转即停止并记录。

## 3. 用户故事

- 作为运营，我希望系统直接抓取政府门户政策列表，稳定提取标题与链接，无需 OCR。
- 作为管理员，我希望系统对常见反爬（动态渲染、Header 校验、限频）有稳健对策，但绝不绕过登录或验证码。

## 4. 输入输出

- **输入**：门户/栏目 URL、`portal_id`、（可选）限频参数
- **输出**：`CrawlResult`

| 字段 | 类型 | 说明 |
|---|---|---|
| `fetch_mode` | `Literal["http","playwright"]` | 实际抓取路径 |
| `html` | `str` | 原始或渲染后 HTML |
| `text_content` | `str` | 提取的可见文本（供 Spec 1 关键词匹配） |
| `page_title` | `str` | 页面标题 |
| `policy_items` | `list[{title, url}]` | 政策条目（DOM/BS 解析） |
| `snapshot_path` | `str` | HTML 快照路径（`data/discovery/snapshots/{portal_id}/{ts}.html`） |
| `final_url` | `str` | 重定向后最终 URL（检测跨域跳转） |
| `restricted` | `bool` | 是否受限停止 |
| `restricted_reason` | `str \| None` | `captcha`/`login`/`http_403`/`http_401`/`http_429`/`cross_domain` |

## 5. 数据模型与接口

```python
@dataclass
class CrawlResult:
    fetch_mode: str
    html: str
    text_content: str
    page_title: str
    policy_items: list[PolicyItem]
    snapshot_path: str
    final_url: str
    restricted: bool
    restricted_reason: str | None

class PortalCrawler:
    def __init__(self, http: OfficialHttpClient, browser: PlaywrightCollector | None = None): ...
    def crawl(self, url: str, portal_id: str) -> CrawlResult: ...
```

`http` 与 `browser` 以构造参数注入，便于单测 mock（对齐项目 pytest + pytest-httpx 模式）。

## 6. 反爬对策（合规范围内）

### 6.1 请求层

- **真实浏览器请求头**：User-Agent（主流浏览器）、Accept、Accept-Language、Accept-Encoding、Referer（同源）
- **请求间隔 + 随机抖动**：≥ `request_interval_seconds` ± 20% 抖动，避免匀速请求特征
- **429/503 退避重试**：指数退避（1s/2s/4s），最多 2 次，尊重 `Retry-After` 响应头
- **公开会话保持**：复用 `httpx.Client` cookies（仅公开会话，不涉及登录）

### 6.2 渲染层

- **默认 HTTP 直接抓取**（`httpx` GET -> HTML），快且轻
- **JS 渲染回退**：HTTP 抓取后 `policy_items` 为空且页面含渲染框架特征（如空列表容器 + JS bundle）-> 回退 Playwright 渲染
- Playwright 渲染后取 `page.content()` 解析 DOM，**不截图、不 OCR**
- **等待策略**：等待列表项选择器出现（`NEXT_PAGE_SELECTORS` 见 `browser.py` 第 23-29 行），非固定 sleep

### 6.3 解析层

- BeautifulSoup 解析列表页 `<a>` 链接与文本
- 复用 `POLICY_TITLE_MARKERS`（`sources/base.py` 第 16-27 行）过滤政策链接
- `listing_item_selectors` / `detail_content_selectors` 配置化，多选择器容错
- 提取可见文本（去 `script`/`style`）供 Spec 1 关键词匹配

### 6.4 合规边界（明确排除）

- 不绕过登录/认证
- 不破解/绕过验证码（触发即停止）
- 不用代理 IP 轮换规避封禁
- 不伪造浏览器指纹（仅标准 UA/请求头，不改 canvas/webdriver 等指纹）
- 遵守 robots.txt 与 `Retry-After`
- 跨白名单域名跳转即停止（`final_url` 不在 `allowed_domains`）

## 7. 处理流程

```
1. HTTP 抓取：httpx GET url（完整请求头 + 会话 cookie）
2. 受限检测（任一命中 -> restricted=True，停止）：
   a. HTTP 401/403/429
   b. 验证码关键词（"验证码"/"captcha"/"人机验证"）
   c. 登录表单（password input + 登录按钮）
   d. final_url 跨出 allowed_domains
3. 解析：BS 解析 HTML，提取 <a> 含 POLICY_TITLE_MARKERS 的链接（title+url）+ 可见文本
4. 渲染回退：若 policy_items 为空且页面有 JS 框架特征 -> Playwright 渲染 -> page.content() -> 重新解析
5. 保存 HTML 快照：data/discovery/snapshots/{portal_id}/{ts}.html
6. 返回 CrawlResult（fetch_mode=http 或 playwright）
```

受限时返回 `restricted=True` 并填充 `restricted_reason`，不抛异常中断整批（由 Spec 1 编排器捕获并记入报告 errors）。

## 8. 与现有实现差异

现有 `PlaywrightCollector`（`browser.py` 第 50 行）已具备 Playwright 导航、渲染、详情抓取与 HTML 快照能力（`parsing/snapshot.py` `save_snapshot` 存原始字节）；`OfficialHttpClient`（`http.py`）已具备 `httpx` 请求。本 spec 新增：发现专用的 `PortalCrawler`（HTTP 优先 + Playwright 回退）、反爬对策（真实请求头/抖动/退避/会话）、政策链接与可见文本提取、面向发现的受限与跨域检测。

**移除**：原 Spec 2 的截图 + OCR 方案，不引入 RapidOCR/PaddleOCR 依赖。

## 9. 验收标准

1. 对静态 HTML 政府门户，HTTP 直接抓取并解析政策标题与链接。
2. 对 JS 动态渲染门户，自动回退 Playwright 渲染后解析 DOM（不截图、不 OCR）。
3. 遇验证码/登录/401/403/429/跨域跳转即停止，`restricted=True` 并记录原因，不绕过。
4. 反爬对策生效：真实请求头、请求间隔+抖动、429/503 退避重试（尊重 `Retry-After`）、公开会话保持。
5. 不绕过登录/验证码、不代理轮换、不伪造指纹；遵守 robots.txt 与限频。
6. HTML 快照存 `data/discovery/snapshots/`，路径回传 Spec 1 写入 `discovery.snapshots`。
7. `PortalCrawler` 可注入 mock http/browser，单测验证解析与受限检测，不依赖真实网络。

## 10. 依赖与关联

- **依赖**：httpx（`OfficialHttpClient`，已有）、Playwright（已集成）、BeautifulSoup4（已有）、`POLICY_TITLE_MARKERS`（复用）。
- **被依赖**：Spec 1（`PortalCrawler.crawl`）。
- **关联**：FR-02 采集（`PlaywrightCollector`/`http` 能力复用）；偏离 PRD D9（截图 OCR -> 直接抓取），需业务确认更新。
