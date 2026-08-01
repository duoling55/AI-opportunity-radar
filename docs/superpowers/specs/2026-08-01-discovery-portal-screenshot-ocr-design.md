# 自动信源发现 - 门户截图 OCR 设计

> 所属：FR-15 自动信源发现（P0 新增）
> 关联 spec：[[01 搜索任务执行]] · [[03 自动合规核查]] · [[04 重要性评分]] · [[05 06页面与信源交互]]
> 上游：FR-02 采集（PlaywrightCollector，复用其浏览器能力）

## 1. 目的与范围

本 spec 是 FR-15 的**叶子能力模块**：对政府门户列表页进行 Playwright 渲染、整页截图、OCR 文本与政策标题提取，并从渲染后 DOM 提取政策 URL，完成标题与 URL 的交叉映射。

**纳入**：Playwright 渲染与等待、整页截图、OCR 文本提取、政策标题识别、DOM 链接提取、标题/URL 映射、受限检测（验证码/登录/403）。

**不纳入**：搜索编排（Spec 1）、合规核查判定（Spec 3）、评分（Spec 4）、前端展示（Spec 5）。本 spec 只产出 `ScanResult` 供编排器消费。

**搜索方式（D9）**：政府门户直接访问 + 浏览器截图 + OCR，规避动态渲染/反爬检测，模拟人工浏览。政策 URL 从渲染后 DOM 提取（链接信息不丢），标题用 OCR 校验。

**合规边界**：仅访问公开页面；遇验证码/登录即停止该门户并记录；遵守限频与 robots.txt；不绕过任何访问控制。

## 2. 功能描述

浏览器渲染政府门户政策栏目列表页后整页截图，OCR 提取文本与政策标题；同时从渲染后 DOM 提取政策链接。标题与 URL 交叉校验：DOM 提供 URL，OCR 校验标题，防止 DOM 混淆或动态渲染丢链接。

## 3. 用户故事

- 作为运营，我希望系统对动态渲染或 DOM 混淆的政府门户也能稳定提取政策标题与链接。
- 作为管理员，我希望遇到验证码或登录要求时系统立即停止，不尝试绕过。

## 4. 输入输出

- **输入**：门户/栏目 URL、`portal_id`、（可选）限频参数
- **输出**：`ScanResult`

| 字段 | 类型 | 说明 |
|---|---|---|
| `screenshot_path` | `str` | 整页截图路径（`data/discovery/screenshots/{portal_id}/{ts}.png`） |
| `ocr_text` | `str` | OCR 提取的全页文本 |
| `page_title` | `str` | 页面标题 |
| `policy_items` | `list[{title, url, title_source}]` | 政策条目；`title_source` 为 `dom`/`ocr`/`both` |
| `restricted` | `bool` | 是否受限停止 |
| `restricted_reason` | `str \| None` | `captcha`/`login`/`http_403`/`http_401`/`http_429` |

## 5. 数据模型与接口

```python
@dataclass
class ScanResult:
    screenshot_path: str
    ocr_text: str
    page_title: str
    policy_items: list[PolicyItem]
    restricted: bool
    restricted_reason: str | None

class PortalScanner:
    def __init__(self, ocr_backend: OcrBackend, browser: PlaywrightCollector | None = None): ...
    def scan(self, url: str, portal_id: str) -> ScanResult: ...
```

`OcrBackend` 为可注入接口，便于单测 mock 与替换 OCR 实现：

```python
class OcrBackend(Protocol):
    def extract_text(self, image_path: str) -> str: ...
```

## 6. OCR 选型

推荐 **RapidOCR（onnxruntime 后端）**：

- 本地运行，中文 PP-OCR 模型，识别质量满足政策标题提取；
- 无 API Key，满足 NFR-03（密钥不经服务传递）；
- Windows + macOS 安装轻量，无需 PaddlePaddle 重依赖（PaddlePaddle 在 macOS 安装成本高）。

备选 **PaddleOCR**（精度略高，但依赖较重）。两者均通过 `OcrBackend` 接口注入，运行时可选。

## 7. 处理流程

```
1. 启动/复用 Playwright browser，导航至 url
2. 等待渲染：优先 networkidle，或等待列表项选择器出现（NEXT_PAGE_SELECTORS 见 browser.py 第 23-29 行）
3. 受限检测（任一命中即抛 PortalRestricted，停止）：
   a. HTTP 401/403/429
   b. 验证码关键词（"验证码"/"captcha"/"人机验证"等）
   c. 登录表单（password input + 登录按钮）
4. 整页截图：page.screenshot(full_page=True) -> data/discovery/screenshots/{portal_id}/{ts}.png
5. DOM 提取政策链接：BeautifulSoup 解析渲染后 HTML，取 <a> 文本含 POLICY_TITLE_MARKERS（sources/base.py 第 16-27 行）的链接，记录 href + 文本
6. OCR 提取：对截图运行 OcrBackend.extract_text，按标题模式匹配提取政策标题
7. 标题/URL 映射：
   - DOM 链接标题与 OCR 标题做相似度匹配（去空白、子串包含）
   - 匹配成功 -> title_source=both
   - 仅 DOM 有 -> title_source=dom（URL 可信）
   - 仅 OCR 有（DOM 未提取到对应链接）-> title_source=ocr，URL 留空并标记，供人工核查
8. 返回 ScanResult
```

受限时返回 `restricted=True` 并填充 `restricted_reason`，不抛异常中断整批（由 Spec 1 编排器捕获并记入报告 errors）。

## 8. 与现有实现差异

现有 `PlaywrightCollector`（`browser.py` 第 50 行）已具备 Playwright 导航、翻页、详情抓取与快照能力，但**未使用 `page.screenshot()`，也无任何 OCR 能力**（`parsing/attachments.py` 的 `extract_attachment_text` 仅支持文本型 PDF/DOCX，遇图片型抛"需 OCR"异常）。本 spec 新增：整页截图、`OcrBackend` 抽象与 RapidOCR 实现、政策标题/URL 交叉映射、面向发现的受限检测。

复用：`PlaywrightCollector` 的 browser 启动与 `NEXT_PAGE_SELECTORS`；`POLICY_TITLE_MARKERS` 标题过滤常量。

## 9. 验收标准

1. 对动态渲染的政府门户列表页，可整页截图并 OCR 提取正文与政策标题。
2. 政策 URL 从渲染后 DOM 提取，链接不丢失；标题用 OCR 交叉校验，`title_source` 标注来源。
3. 遇验证码/登录/401/403/429 即停止该门户，`restricted=True` 并记录原因，不尝试绕过。
4. `OcrBackend` 可注入，单测可用 mock 后端验证标题/URL 映射逻辑，不依赖真实 OCR。
5. 截图存 `data/discovery/screenshots/{portal_id}/`，路径回传 Spec 1 写入 `discovery.screenshots`。
6. 遵守限频：单门户内请求间隔 ≥ 门户种子或默认限频值。

## 10. 依赖与关联

- **依赖**：Playwright（已集成）、RapidOCR（新增依赖）、`POLICY_TITLE_MARKERS`（复用）。
- **被依赖**：Spec 1（`PortalScanner.scan`）。
- **关联**：FR-02 采集（`PlaywrightCollector` 浏览器能力复用）。
