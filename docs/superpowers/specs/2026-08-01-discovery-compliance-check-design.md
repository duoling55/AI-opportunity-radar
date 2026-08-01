# 自动信源发现 - 自动合规核查设计

> 所属：FR-15 自动信源发现（P0 新增）
> 关联 spec：[[01 搜索任务执行]] · [[02 门户截图OCR]] · [[04 重要性评分]] · [[05 06页面与信源交互]]
> 上游：FR-01 合规状态机（compliance.py ComplianceSource）、NFR-04 采集合规

## 1. 目的与范围

本 spec 是 FR-15 的**叶子能力模块**：对每个发现信源自动执行**被动**合规核查，输出核查结论、明细与启用建议。

**纳入**：7 项被动核查（域名归属/可访问性/登录/验证码/robots/限频线索/栏目结构）、`check_result`/`check_details`/`recommendation` 判定。

**不纳入**：搜索编排（Spec 1）、截图 OCR（Spec 2）、评分（Spec 4）、前端展示与人工确认（Spec 5）。本 spec 只产出 `ComplianceReport`。

**合规边界（强制）**：仅被动检测，不绕过任何访问控制。不提交表单、不模拟登录、不尝试验证码、不轮换指纹/代理。验证码或登录触发即标记并停止深入。

## 2. 功能描述

系统对每个发现信源自动核查判断（可访问性/登录/robots/限频等），输出核查报告与启用建议，供用户基于报告确认启用，确保合规。

## 3. 用户故事

- 作为管理员，我希望系统对发现的信源自动核查，我基于核查报告确认启用，确保合规。
- 作为管理员，我希望 `not_recommended` 信源默认不启用，人工确认前不得采集。

## 4. 输入输出

- **输入**：发现信源（`url`、`domain`、`sample_policies`、Spec 2 的 `ScanResult` 受限信息）
- **输出**：`ComplianceReport`

| 字段 | 类型 | 说明 |
|---|---|---|
| `check_result` | `Literal["pass","needs_attention","not_recommended"]` | 核查结论 |
| `check_details` | `object` | 七项核查明细（见 §6） |
| `recommendation` | `Literal["建议启用","需人工关注","不建议"]` | 启用建议 |

## 5. 处理流程

```
对每个发现信源，依次执行 7 项被动核查，汇总判定：
1. 域名归属：是否 *.gov.cn
2. 可访问性：HTTP 状态码、是否公开可访问
3. 登录要求：是否需要登录/认证
4. 验证码：是否触发验证码（触发即标记，不绕过）
5. robots.txt：读取并解析，判断目标栏目是否允许采集
6. 限频线索：响应头 Retry-After / RateLimit、页面反爬声明
7. 栏目结构：识别列表页/详情页结构，样例政策数量
-> 输出 check_result + check_details + recommendation
```

## 6. 数据模型与接口

### 6.1 七项核查明细（check_details）

| 项 | 字段 | 判定方式 |
|---|---|---|
| 域名归属 | `domain_owner: "gov" \| "other"` | 域名后缀是否 `*.gov.cn` |
| 可访问性 | `accessibility: {status_code, public}` | HTTP GET/HEAD 状态码、是否无需认证即可访问 |
| 登录要求 | `login_required: bool` | 页面是否出现登录表单/登录跳转 |
| 验证码 | `captcha_triggered: bool` | 是否触发验证码（取 Spec 2 `restricted_reason` 或复查） |
| robots.txt | `robots: {allowed, raw}` | 读取 `/robots.txt`，解析目标栏目路径是否 Disallow |
| 限频线索 | `rate_limit_hints: {retry_after, rate_limit_header, anti_scraping_notice}` | 响应头与页面反爬声明 |
| 栏目结构 | `column_structure: {list_page, detail_page, sample_count}` | 列表页/详情页结构识别、样例政策数量 |

### 6.2 判定规则

- `not_recommended`：域名非政府 **或** 触发验证码 **或** 需登录 **或** robots 禁止采集。
- `needs_attention`：限频未知 **或** 样例政策数量 < 3 / 列表页与详情页结构无法识别 **或** 存在反爬声明但未明确禁止。
- `pass`：政府域名 + 公开可访问 + robots 允许 + 无验证码/登录。

`recommendation` 映射：`pass`→建议启用、`needs_attention`→需人工关注、`not_recommended`→不建议。

### 6.3 接口

```python
class ComplianceChecker:
    def check(self, source: CandidateSource, scan_result: ScanResult | None = None) -> ComplianceReport: ...
```

`ComplianceChecker` 内部用 `httpx`（复用 `OfficialHttpClient`，`http.py`）做 HEAD/GET 与 robots 读取；HTTP 调用须带超时与重试限制（对齐全局规则：超时、重试、降级）。

## 7. 与现有实现差异

现有项目无自动合规核查能力。`compliance.py`（第 133-189 行 `ComplianceSource`）定义了人工登记的合规台账与 `candidate/verified/retired` 状态机，但所有核查项均由人工填写，无自动检测。本 spec 新增 7 项被动自动核查与判定规则，核查结果写入 `discovery.check_details`，作为人工确认的依据，**不取代**人工确认（启用仍须经 Spec 5 人工 promote）。

## 8. 验收标准

1. 对每个发现信源输出 7 项核查明细（域名归属/可访问性/登录/验证码/robots/限频线索/栏目结构）。
2. 输出 `check_result`（pass/needs_attention/not_recommended）与 `recommendation`（建议启用/需人工关注/不建议）。
3. `not_recommended` 信源默认不启用；人工确认前不得采集。
4. 仅被动检测：不提交表单、不模拟登录、不绕过验证码；遇验证码/登录即标记并停止深入。
5. robots.txt 读取并解析；目标栏目被 Disallow 时判为 `not_recommended`。
6. HTTP 调用带超时与限频；单信源核查失败不中断整批，失败项记入 `check_details`。

## 9. 依赖与关联

- **依赖**：httpx（已有，`OfficialHttpClient`）、`compliance.py` 合规模型理念。
- **被依赖**：Spec 1（`ComplianceChecker.check`）；Spec 4（消费 `check_result` 作为"合规可采集性"评分维度输入）。
- **关联**：FR-01 合规状态机、NFR-04 采集合规。
