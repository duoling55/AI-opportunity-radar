# 自动信源发现 - 搜索任务执行（编排器）设计

> 所属：FR-15 自动信源发现（P0 新增）
> 关联 spec：[[02 门户直接抓取]] · [[03 自动合规核查]] · [[04 重要性评分]] · [[05 06页面与信源交互]]
> 上游：FR-05 知识库管理（关键词来源）、FR-01 信源管理（Source 模型与状态机）

## 1. 目的与范围

本 spec 是 FR-15 自动信源发现的**编排核心**。它读取知识库关键词与政府门户种子，驱动门户直接抓取（Spec 2），识别政策栏目 URL 并预填信源元数据，对每个候选调用合规核查（Spec 3）与重要性评分（Spec 4），产出候选信源清单与发现报告。

**纳入**：搜索任务编排、关键词与门户种子加载、候选信源预填与落库、发现报告生成、CLI 子命令与异步任务接入。

**不纳入**：门户直接抓取本身（Spec 2）、合规核查判定（Spec 3）、评分计算（Spec 4）、前端页面与提升流程（Spec 5）。本 spec 只定义对它们的调用契约。

**搜索方式（D9，偏离见 Spec 2）**：不使用搜索引擎 API；采用政府门户直接抓取网页内容 + 反爬对策（HTTP 优先、Playwright 渲染回退、稳健请求策略），不使用截图 OCR。详见 Spec 2。

**合规边界**：仅访问公开页面；遇验证码/登录即停止该门户并记录；遵守限频与 robots.txt；不绕过任何访问控制；未核验信源绝不进入 FR-02 采集可选列表。

## 2. 模块总览与依赖

```
              ┌───────────────────────────────┐
              │ Spec 5: 06 页面与信源交互        │
              └───────────────┬───────────────┘
                      展示 / 审核 / 提升
        ┌──────────────────────────────────────┐
        │   Spec 1: 搜索任务执行（编排器）        │
        │   关键词->门户抓取->候选->核查->评分->报告  │
        └──┬─────────────┬─────────────────┬──┘
           │调用          │调用              │调用
   ┌───────▼──────┐ ┌────▼─────────┐ ┌──────▼──────┐
   │ Spec 2       │ │ Spec 3       │ │ Spec 4      │
   │ 门户直接抓取  │ │ 自动合规核查  │ │ 重要性评分   │
   └──────────────┘ └──────────────┘ └─────────────┘
```

- Spec 2/3/4 为叶子能力，互不依赖（Spec 4 仅消费 Spec 3 的报告作为输入参数，不反向调用）。
- Spec 1 编排器调用三者，是唯一集成点。
- Spec 5 前端消费 Spec 1 产出的候选与报告。

**关键词来源依赖（FR-05）**：FR-15 搜索由知识库 25 类标签的"政策关键词/典型表述"驱动。FR-05 知识库 Excel 导入同样是 P0 新增、尚未实现。为此定义 `KeywordSource` Protocol 解耦：FR-05 落地后实现之；在此之前提供 `FallbackKeywordSource`，读取 `config/discovery_keywords.json`（种子词见 §6.2），保证本 spec 可独立实现与测试。

## 3. 功能描述

基于知识库关键词，自动在政府门户搜索政策，发现新的政策信源/栏目，加入候选清单。系统对发现信源自动进行合规核查与重要性评分，输出核查报告、评分与启用建议，由用户手动判断哪些信源加入启用。未确认信源绝不被采集任务选中。

## 4. 用户故事

- 作为运营，我希望系统根据知识库关键词自动搜索政府网站，发现更多政策信源，减少手动找信源的成本。
- 作为管理员，我希望系统对发现的信源自动核查判断（可访问性/登录/robots/限频等），我基于核查报告确认启用，确保合规。
- 作为运营，我希望看到每个候选信源的重要性评分和评分要素（如国家>地方、租赁>其他金融），以便手动判断哪些值得加入。

## 5. 输入输出

- **输入**：知识库标签选择（默认全部，可勾选子集）+ 政府门户种子范围（`config/discovery_portals.json`，限定 `*.gov.cn` 及省级政府门户）+ 搜索模式（直接抓取）
- **输出**：候选信源清单（写入 `config/compliance_sources.json`，`origin=discovery`、`phase=candidate`、`enabled=false`）+ 发现报告（`data/discovery/{job_id}-report.json`，含关键词、命中域名、样例政策、HTML 快照路径）

## 6. 数据模型与接口

### 6.1 候选信源扩展（compliance.py ComplianceSource）

`ComplianceSource` 新增两个字段（详见 Spec 5 §6 数据模型变更）：

| 字段 | 类型 | 说明 |
|---|---|---|
| `origin` | `Literal["manual","discovery"]` | 来源标记；默认 `manual`，FR-15 发现的为 `discovery` |
| `discovery` | `DiscoveryMeta \| None` | 仅 `origin=discovery` 时填充 |

`DiscoveryMeta` 结构：

| 字段 | 类型 | 说明 |
|---|---|---|
| `keywords` | `list[str]` | 命中的搜索关键词 |
| `discovered_at` | `date` | 发现日期 |
| `portal_seed_id` | `str` | 来源门户种子 ID |
| `admin_level` | `Literal["国家","省","市"]` | 行政层级（取自门户种子，供 Spec 4 评分） |
| `sample_policies` | `list[{title, url, matched_keywords}]` | 样例政策（≤5 条） |
| `snapshots` | `list[str]` | HTML 快照文件路径 |
| `check_result` | `Literal["pass","needs_attention","not_recommended"]` | Spec 3 核查结论 |
| `check_details` | `object` | Spec 3 七项核查明细 |
| `recommendation` | `Literal["建议启用","需人工关注","不建议"]` | Spec 3 启用建议 |
| `priority_score` | `int` (0-100) | Spec 4 重要性总分 |
| `priority_level` | `Literal["高","中","低"]` | Spec 4 优先级分级 |
| `score_breakdown` | `list[{dimension, score, max, reason}]` | Spec 4 评分要素 |

候选写入 `compliance_sources.json`，复用其 `candidate/verified/retired` 状态机；初始 `phase=candidate`、`enabled=false`、`verified_at=null`。

### 6.2 关键词来源

```python
class KeywordSource(Protocol):
    def get_search_keywords(self) -> list[SearchKeyword]: ...
```

`SearchKeyword`：`{ text: str, tag: str, signal_strength: str | None }`（tag 为 25 类标签之一）。

`FallbackKeywordSource` 读取 `config/discovery_keywords.json`，种子词包含：
- `POLICY_TITLE_MARKERS`（通知/办法/细则/指南/意见/方案/公告/公示/规划 等，见 `sources/base.py` 第 16-27 行）
- `business_industries.json` 的 12 个行业标签
- 融资术语：设备更新、技术改造、智能化改造、融资租赁、绿色租赁、售后回租、设备直租、专精特新、智能制造、产业升级 等

> FR-05 落地后，`KbKeywordSource` 从已发布知识库的"政策关键词/典型表述"列读取，替换 Fallback。

### 6.3 门户种子（config/discovery_portals.json）

| 字段 | 说明 |
|---|---|
| `portal_id` | 门户稳定标识 |
| `display_name` | 门户名称 |
| `region` | 区域（国家/浙江/江苏/…） |
| `entry_url` | 政策栏目入口 URL |
| `admin_level` | 国家/省/市 |
| `gov_domain` | 政府域名（须为 `*.gov.cn`） |

种子由运营维护，初始覆盖国家级与浙江/江苏省级政府门户。

### 6.4 发现报告（data/discovery/{job_id}-report.json）

| 字段 | 类型 | 说明 |
|---|---|---|
| `job_id` | `str` | 任务 ID（与 `data/ui_jobs/{job_id}.log` 对应） |
| `started_at` / `finished_at` | `datetime` | 起止时间 |
| `keywords_used` | `list[str]` | 实际使用关键词 |
| `portals_scanned` | `list[{portal_id, url, status, policies_found}]` | 各门户扫描结果 |
| `candidates` | `list[str]` | 发现的 source_id 列表 |
| `stats` | `{portals_scanned, policies_extracted, candidates_found, restricted_stopped}` | 统计 |
| `errors` | `list[{portal_id, reason, detail}]` | 受限停止与异常记录 |

### 6.5 编排器接口

```python
class DiscoveryOrchestrator:
    def __init__(self, crawler: PortalCrawler, checker: ComplianceChecker,
                 scorer: ImportanceScorer, keyword_source: KeywordSource): ...
    def run(self, keyword_tags: list[str] | None, portal_ids: list[str] | None,
            mode: str = "direct_crawl") -> DiscoveryReport: ...
```

三个依赖以构造参数注入，便于单测 mock（对齐项目 pytest + pytest-httpx 模式）。

### 6.6 CLI 子命令

`cli.py` `_parser()` 新增子命令：

```
opportunity-radar search-sources [--keywords all|tag1,tag2] [--portals all|portal_id] [--mode direct-crawl]
```

UI 经 `POST /api/discovery/search`（Spec 5）调 `_start_job()`（`ui_server.py` 第 358-394 行）启动该子进程；前端复用 `/api/jobs` 轮询进度（`app.js` 第 777-784 行）。

## 7. 处理流程

```
1. 读取关键词集合（KeywordSource.get_search_keywords()，按 keyword_tags 过滤）
2. 加载门户种子（config/discovery_portals.json，按 portal_ids 过滤）
3. 对每个门户：
   a. 调 PortalCrawler.crawl(entry_url)（Spec 2）
   b. 受限（CrawlResult.restricted=True）-> 记录 errors，停止该门户，不深入
   c. 取 CrawlResult.policy_items（标题 + URL）与 text_content
4. 关键词匹配：对 CrawlResult.policy_items 标题与 text_content 与关键词集合匹配，筛选出命中的政策条目
5. 候选生成：每个被扫描的门户栏目页（entry_url）若含 ≥1 条命中政策，即生成一个候选信源；list_url = 该栏目页 URL；预填 display_name、allowed_domains、样例政策（命中条目，≤5）、命中关键词、admin_level（取自门户种子）
   > P0 范围内 entry_url 直接指向政策栏目列表页；从门户首页索引递归跟进子栏目列表的发现留待后续增强。
6. 对每个候选：
   a. 调 ComplianceChecker.check(source)（Spec 3）-> check_result / check_details / recommendation
   b. 调 ImportanceScorer.score(source, samples, compliance_report)（Spec 4）-> priority_score / level / breakdown
7. 写入 compliance_sources.json（origin=discovery, phase=candidate, enabled=false, discovery=DiscoveryMeta）
8. 写发现报告 data/discovery/{job_id}-report.json
```

## 8. 状态流转

```
discovered（候选，candidate, enabled=false）
   ↓ 系统自动核查判断 + 重要性评分（输出报告、评分与建议）
   ↓ 人工基于核查报告与评分要素确认启用 + 限频登记（Spec 5）
verified（已核验, enabled=true，可被采集任务选中）
   ↓ 停用/弃用
retired
```

未核验（discovered/candidate）的信源**绝不**出现在 FR-02 采集任务的可选列表中。

## 9. 与现有实现差异

现有项目无此功能。P0 新增：搜索编排模块、关键词来源接口与 Fallback、门户种子配置、`DiscoveryMeta` 字段、发现报告、`search-sources` CLI 子命令。复用 `compliance_sources.json` 的合规状态机理念（见 `compliance.py` 第 133-189 行 `ComplianceSource`）与 `_start_job()` 异步任务模式（`ui_server.py` 第 358-394 行）。

## 10. 验收标准

1. 可选择知识库标签（默认全部）发起搜索任务，结果限定政府域名（`*.gov.cn`）。
2. 采用直接抓取方式（Spec 2，HTTP 优先 + Playwright 回退）提取政府门户内容，遇验证码/登录/跨域即停止该门户并记录于报告。
3. 发现的信源写入 `compliance_sources.json`，`origin=discovery`、`phase=candidate`、`enabled=false`，不被采集任务选中。
4. 每个候选带 Spec 3 核查报告（7 项 + 启用建议）与 Spec 4 评分（6 维度 + 总分 + 优先级 + 要素）。
5. 发现报告含关键词、命中域名、样例政策、HTML 快照路径，可查可导出。
6. 搜索任务经 `_start_job()` 异步执行，前端可轮询进度；单门户失败不中断整批。
7. `FallbackKeywordSource` 可在 FR-05 未落地时独立驱动搜索，单测可 mock 三个子能力。

## 11. 依赖与关联

- **依赖**：Spec 2（PortalCrawler）、Spec 3（ComplianceChecker）、Spec 4（ImportanceScorer）、FR-05（KeywordSource，暂由 Fallback 替代）。
- **被依赖**：Spec 5（前端消费候选与报告）。
- **关联**：FR-01（Source 模型与状态机）、FR-02（采集门控，由 Spec 5 落地）。
