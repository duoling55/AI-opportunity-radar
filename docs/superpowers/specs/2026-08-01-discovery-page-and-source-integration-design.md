# 自动信源发现 - 06 页面与信源交互设计

> 所属：FR-15 自动信源发现（P0 新增）
> 关联 spec：[[01 搜索任务执行]] · [[02 门户截图OCR]] · [[03 自动合规核查]] · [[04 重要性评分]]
> 上游：FR-01 信源管理、FR-02 采集任务（信源选择与门控）

## 1. 目的与范围

本 spec 承接 FR-15 的**全部前端功能与信源集成**：在左侧导航新增 `06 信源搜索` 页面，作为发现模块的唯一入口；提供搜索发起、候选列表、核查报告与评分要素展示、人工审核、提升为正式信源；与 `01 信源编辑` 交互；并落地采集门控。

**纳入**：06 页面（HTML/JS/CSS）、发现相关后端 API、审核与提升流程、`compliance_sources.json` 与 `sources.json` 的同步、01 信源编辑的约束放宽与 discovery 信源展示、通用 HTML 适配器、FR-02 采集选择的门控。

**不纳入**：搜索执行（Spec 1）、截图 OCR（Spec 2）、核查判定（Spec 3）、评分计算（Spec 4）。本 spec 消费它们的产出。

**交互模型（已确认）**：06 负责发现 + 自动核查 + 评分 + 人工审核；确认后提升写入信源注册表（`compliance_sources.json` 的 `candidate->verified`），并同步至 `sources.json` 使 01 可见可编辑、采集任务可选；新信源用通用 HTML 适配器采集，无需专用适配器。

## 2. 功能描述

06 信源搜索页承载发现模块全部功能：发起搜索任务、查看候选信源清单、展开核查报告与评分要素、查看样例政策与截图、人工审核（确认启用/驳回/标记关注）、提升为正式信源。提升后的信源在 01 信源编辑可见可编辑，并受采集门控约束（未核验绝不采集）。

## 3. 用户故事

- 作为运营，我希望在 06 页面发起搜索、查看候选、查看核查报告与评分要素，并确认启用哪些信源。
- 作为管理员，我希望确认启用的信源自动进入 01 信源编辑可维护，并立即可被采集任务选中。
- 作为管理员，我希望 `not_recommended` 信源默认不启用，需二次确认才能提升。
- 作为运营，我希望未核验的信源绝不出现在采集任务的可选列表中。

## 4. 前端设计

### 4.1 导航与页面（index.html / app.js）

`index.html` `<nav>`（第 27-43 行）新增按钮：

```html
<button class="nav-item" data-page="search"><b>06</b><span>信源搜索</span></button>
```

并新增 `<section id="page-search" class="page">`。`app.js` `pages` 字典（第 29-35 行）新增：

```javascript
search: ["信源搜索", "基于知识库关键词自动发现政府政策信源，核查评分后确认启用。"],
```

`setPage()`（第 172-183 行）加 `search` 分支，进入时拉取候选列表与最近任务。

### 4.2 06 页面区块

| 区块 | 内容 |
|---|---|
| 搜索发起区 | 知识库标签勾选（默认全部）、门户种子选择（默认全部）、搜索模式（截图 OCR）、"发起搜索"按钮、任务进度（轮询 `/api/jobs`） |
| 候选列表区 | 每条：名称、域名、栏目 URL、核查结果徽标（pass/needs_attention/not_recommended）、优先级（高/中/低）、评分总分、样例政策数、截图缩略图、"展开详情"与审核按钮 |
| 详情抽屉 | 核查报告 7 项明细、评分要素 6 维度（含 reason）、样例政策（标题/URL/命中关键词）、截图大图、审核操作（确认启用/驳回/标记关注 + 备注） |

样式沿用 `styles.css` 既有卡片/徽标风格；核查结果与优先级用颜色徽标区分。

## 5. 后端 API（ui_server.py）

`RadarRequestHandler` 的 `do_GET`/`do_POST`（第 642-713 行手工分发）新增分支：

| 方法 | 路由 | 说明 |
|---|---|---|
| POST | `/api/discovery/search` | 发起搜索任务，调 `_start_job()` 启动 `search-sources` 子进程（Spec 1） |
| GET | `/api/discovery/candidates` | 候选列表（读 `compliance_sources.json` where `origin=discovery`） |
| GET | `/api/discovery/candidates/{id}` | 单候选详情（含 `discovery` 全字段） |
| POST | `/api/discovery/candidates/{id}/review` | 审核：`confirm`/`reject`/`watch` + 备注 |
| POST | `/api/discovery/candidates/{id}/promote` | 提升为正式信源（见 §6） |
| GET | `/api/discovery/reports/{job_id}` | 发现报告（Spec 1） |

## 6. 审核与提升流程

### 6.1 审核动作

- **确认启用（confirm）**：触发 promote（见 §6.2），`candidate->verified`、`enabled=true`，同步 `sources.json`。
- **驳回（reject）**：置 `phase=retired`、`enabled=false`，记录驳回原因（必填）与审核人、时间；该信源不再出现在候选待审列表，但保留记录可查。
- **标记关注（watch）**：保持 `candidate`，写入关注备注，供后续复查。

### 6.2 提升流程（promote）

```
promote(source_id):
  1. 校验：compliance_sources.json 中 origin=discovery 且 phase=candidate
  2. 若 check_result=not_recommended -> 需二次确认（前端弹窗强提示），否则拒绝
  3. compliance_sources.json: phase->verified, enabled=true, verified_at=today, owner=当前用户
  4. 同步写入 sources.json：
     - source_id、display_name、region、list_urls(=栏目URL)、allowed_domains、
       request_interval_seconds(=discovery 限频或默认)、adapter_version="generic"、origin="discovery"
  5. 返回结果，前端刷新候选列表与 01 信源列表
```

`not_recommended` 信源默认不启用；强制提升须二次确认并在审核历史记录"override not_recommended"。

## 7. 01 信源编辑集成

### 7.1 放宽新增约束

`ui_server.py` `_validate_sources`（第 166-167 行）当前强制 `seen == original_ids`，即不能新增/删除信源。改为：

- 允许新增 `origin=discovery` 的信源（由 promote 写入）；
- 仍禁止手动新增无适配器的任意信源（手动新增须经专用适配器，保留 FR-01 的 candidate->verified 流程）；
- `source_id` 不可修改；`adapter_version="generic"` 的信源允许编辑字段（list_urls、allowed_domains、rate_limit 等）。

### 7.2 01 展示 discovery 信源

`#page-sources`（`index.html` 第 64-92 行）表格展示 discovery 信源时带 `origin`/`phase` 徽标；`enabled` 仅当 `phase=verified` 时可置 `true`。01 与 06 以 `compliance_sources.json` 为 discovery 信源的**唯一真源**；`sources.json` 中的 discovery 条目是由 promote 生成、01 编辑时同步刷新的**运行时投影**。promote 与 01 编辑均为双写（先写 `compliance_sources.json`，再同步 `sources.json`），避免两文件漂移。

### 7.3 通用 HTML 适配器

新增 `src/opportunity_radar/sources/generic.py`：

```python
class GenericGovSource(GenericHtmlSource):
    """按 sources.json 配置实例化的通用政府信源适配器，无需专用适配器文件。"""
```

继承 `GenericHtmlSource`（`sources/base.py` 第 71 行），从配置读取 `list_urls`、`listing_item_selectors`、`detail_content_selectors`（提供面向政府门户的默认选择器，可被配置覆盖）。`sources/registry.py` 按 `adapter_version="generic"` 或 `origin=discovery"` 路由到 `GenericGovSource`。

## 8. 采集门控（FR-02 联动）

- FR-02 信源选择过滤 `phase=verified AND enabled=true`；
- 采集前校验信源在 `compliance_sources.json` 为 `verified` 且 `enabled=true`，否则不发送网络请求并给出"未核验/未启用"错误（对齐既有合规来源设计 `2026-07-29-compliant-source-registry-design.md` 第 5 节运行时判定）；
- 未核验（`candidate`/`discovered`）信源**绝不**出现于采集任务可选列表。

## 9. 数据模型变更

### 9.1 SourceConfig（config.py 第 11-26 行）

新增字段：

| 字段 | 类型 | 说明 |
|---|---|---|
| `origin` | `str` | `manual`/`discovery`；默认 `manual` |

### 9.2 ComplianceSource（compliance.py 第 133-189 行）

新增字段：

| 字段 | 类型 | 说明 |
|---|---|---|
| `origin` | `Literal["manual","discovery"]` | 默认 `manual` |
| `discovery` | `DiscoveryMeta \| None` | 仅 `origin=discovery` 填充；结构见 Spec 1 §6.1 |

### 9.3 配置文件

- `config/compliance_sources.json`：候选与已验证 discovery 信源（主数据）。
- `config/sources.json`：运行时可采集子集；discovery 信源带 `origin=discovery`、`adapter_version="generic"`。
- `config/discovery_portals.json`：门户种子（Spec 1）。
- `config/discovery_keywords.json`：Fallback 关键词（Spec 1）。

## 10. 状态流转

```
discovered（candidate, enabled=false，06 可见可审核）
   ↓ 人工 confirm -> promote（not_recommended 需二次确认）
verified（enabled=true，01 可见可编辑，采集任务可选）
   ↓ 停用/弃用
retired（enabled=false）
```

## 11. 与现有实现差异

| 现状 | P0 改造 |
|---|---|
| 左侧导航仅 01-05 五页 | 新增 06 信源搜索页（`index.html`/`app.js`/`styles.css`） |
| `compliance_sources.json` 无 UI 编辑入口，仅手改 | 06 页提供候选展示/审核/提升 API |
| 01 信源编辑不能新增信源（`_validate_sources` 强制 `seen==original_ids`） | 放宽：允许 `origin=discovery` 信源由 promote 写入并编辑 |
| `sources.json`/`SourceConfig` 无 `origin`/`phase` | 新增 `origin`；phase 以 `compliance_sources.json` 为准 |
| 信源采集需专用适配器文件 | 新增 `GenericGovSource` 通用适配器，按配置实例化 |
| FR-02 采集选择无 phase 门控 | 新增 `verified AND enabled` 门控 |

## 12. 验收标准

1. 左侧导航出现 `06 信源搜索`，进入后可发起搜索任务（选标签/门户/模式）并查看进度。
2. 候选列表展示名称、域名、栏目 URL、核查结果徽标、优先级、评分总分、样例政策数、截图缩略图。
3. 详情抽屉展示核查报告 7 项、评分要素 6 维度（含 reason）、样例政策、截图。
4. 可对候选执行确认启用/驳回/标记关注；`not_recommended` 信源默认不启用，强制提升需二次确认。
5. 确认启用后：`compliance_sources.json` 的 `phase->verified`、`enabled=true`；`sources.json` 同步写入该信源（`origin=discovery`、`adapter_version=generic`）。
6. 01 信源编辑可见并可编辑该 discovery 信源（带 origin/phase 徽标）；`enabled` 仅 `verified` 时可置 `true`。
7. 未核验（candidate/discovered）信源不出现在 FR-02 采集可选列表；强制选择时给出"未核验/未启用"错误且不发送网络请求。
8. discovery 信源经 `GenericGovSource` 通用适配器可被采集（对齐 FR-02 验收）。

## 13. 依赖与关联

- **依赖**：Spec 1（候选与报告产出）、Spec 2/3/4（展示数据）、`_start_job()` 异步模式、FR-01 合规状态机。
- **被依赖**：FR-02 采集（门控与通用适配器）。
- **关联**：FR-01 信源管理、FR-02 采集任务、既有 `2026-07-29-compliant-source-registry-design.md` 运行时判定。
