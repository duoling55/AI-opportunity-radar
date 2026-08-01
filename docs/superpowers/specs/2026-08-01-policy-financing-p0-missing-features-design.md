# 政策融资需求识别系统 P0 缺失功能设计 Spec

> **版本：** V1.0  
> **日期：** 2026-08-01  
> **状态：** 待实现  
> **实现时限：** 3 小时  

---

## 0. 执行摘要

### 0.1 背景

当前项目已实现采集、解析、分析、导出核心链路，但缺少两个 P0 功能：
1. **知识库管理**：Excel 知识库的导入、校验、版本化
2. **人工审核**：对分析结果的通过/驳回/退回流程

### 0.2 实现策略

采用简化版设计，聚焦 MVP 闭环：
- 知识库：只实现文件导入、格式校验、版本列表，不实现 Web UI 编辑器
- 人工审核：只实现审核结果记录（JSON 文件），不实现实时审核页面

---

## 1. 知识库管理（简化版）

### 1.1 功能范围

| 包含 | 不包含 |
| --- | --- |
| Excel 文件上传（命令行/本地文件） | Web UI 上传界面 |
| 字段格式校验 | 在线编辑规则 |
| 版本保存与列表 | 版本对比 Diff |
| 加载指定版本用于分析 | 回滚操作 |

### 1.2 数据模型

```python
@dataclass
class KnowledgeRule:
    rule_id: str                    # 唯一标识，如 "device-update-001"
    policy_trigger_type: str        # 触发类型，如 "设备更新、以旧换新"
    keywords_or_typical_phrases: list[str]  # 关键词列表
    enterprise_behavior: str        # 企业行为，如 "淘汰旧设备并采购新设备"
    primary_financing_need: str     # 主要融资需求，如 "设备融资、直租、售后回租"
    suitable_financial_leasing_product: str  # 适配产品
    applicable_industry_examples: list[str] # 适用行业示例
    signal_strength: str            # 信号强度：很强/中等/弱
    identification_notes: str       # 识别备注


@dataclass
class KnowledgeBase:
    version: str                    # 版本号，如 "v2026-08-01-001"
    rules: list[KnowledgeRule]      # 规则列表
    created_at: datetime            # 创建时间
    created_by: str                 # 创建人
```

### 1.3 Excel 格式要求

| 列名 | 必填 | 校验规则 |
| --- | --- | --- |
| rule_id | 是 | 非空，唯一 |
| policy_trigger_type | 是 | 非空 |
| keywords_or_typical_phrases | 是 | 非空，逗号分隔 |
| enterprise_behavior | 是 | 非空 |
| primary_financing_need | 是 | 非空 |
| suitable_financial_leasing_product | 是 | 非空 |
| applicable_industry_examples | 否 | 逗号分隔 |
| signal_strength | 是 | 枚举：很强/中等/弱 |
| identification_notes | 否 | - |

### 1.4 文件存储

```
data/
└─ knowledge/
   ├─ knowledge-v2026-08-01-001.json
   ├─ knowledge-v2026-08-01-002.json
   └─ versions.json  # 版本索引
```

### 1.5 接口设计

```python
# 导入 Excel 并保存版本
def import_knowledge_base(excel_path: Path, version: str, created_by: str) -> KnowledgeBase

# 加载指定版本
def load_knowledge_base(version: str = "latest") -> KnowledgeBase | None

# 列出所有版本
def list_knowledge_versions() -> list[dict]

# 校验 Excel 格式
def validate_excel_knowledge(excel_path: Path) -> tuple[list[dict], list[str]]
```

---

## 2. 人工审核（简化版）

### 2.1 功能范围

| 包含 | 不包含 |
| --- | --- |
| 审核结果 JSON 记录 | Web UI 审核页面 |
| 通过/驳回/退回状态 | 实时修改分析结果 |
| 审核原因记录 | 批量审核 |
| 审核历史可追溯 | 审核统计看板 |

### 2.2 审核状态枚举

```python
ReviewStatus = Literal["pending", "approved", "rejected", "returned"]

REJECT_REASONS = [
    "误命中",           # 关键词命中但上下文不支持
    "行业不符",         # 行业映射错误
    "无实际投入",       # 无企业资本开支行为
    "政策失效",         # 已过期或废止
    "证据不足",         # 无可定位原文证据
    "其他",
]
```

### 2.3 数据模型

```python
@dataclass
class ReviewRecord:
    review_id: str                    # 审核记录 ID
    policy_id: str                    # 政策 ID
    opportunity_index: int            # 机会索引（一篇政策可能多个机会）
    original_opportunity: dict        # 原始分析结果（JSON 快照）
    status: ReviewStatus              # 审核状态
    reject_reason: str | None         # 驳回原因
    reviewer_comment: str             # 审核意见
    reviewer_id: str                  # 审核人 ID
    reviewed_at: datetime             # 审核时间
    modified_fields: dict | None      # 修改的字段（如修改后通过）
```

### 2.4 文件存储

```
data/
└─ reviews/
   ├─ review-2026-08-01-001.json
   ├─ review-2026-08-01-002.json
   └─ review-index.json  # 审核索引（policy_id -> review_id）
```

### 2.5 接口设计

```python
# 创建审核记录
def create_review_record(
    policy_id: str,
    opportunity: IndustryOpportunity,
    status: ReviewStatus,
    reviewer_id: str,
    comment: str,
    reject_reason: str | None = None,
) -> ReviewRecord

# 加载政策的审核记录
def load_review_records(policy_id: str) -> list[ReviewRecord]

# 列出所有审核记录
def list_review_records(
    status: ReviewStatus | None = None,
    reviewer_id: str | None = None,
) -> list[ReviewRecord]
```

---

## 3. 与现有代码集成

### 3.1 分析流程集成

```python
# 在 run_pipeline 中，分析前加载知识库
knowledge_base = load_knowledge_base(version="latest")
rules = [rule.to_dict() for rule in knowledge_base.rules]

# 分析后，创建待审核记录
for opportunity in analysis.opportunities:
    review = create_review_record(
        policy_id=document.policy_id,
        opportunity=opportunity,
        status="pending",
        reviewer_id="system",
        comment="AI 自动分析结果，待人工审核",
    )
```

### 3.2 Excel 导出集成

在导出的 Excel 中增加审核状态列：
- `审核状态`：待审核/已通过/已驳回/已退回
- `驳回原因`：如适用
- `审核人`：审核人 ID
- `审核时间`：ISO 8601 时间

---

## 4. 验收标准

### 4.1 知识库管理

- [ ] 可导入符合格式的 Excel 文件，生成 JSON 版本
- [ ] 校验失败时返回具体错误（缺列、空值、枚举非法）
- [ ] 可列出所有版本及创建时间、规则数
- [ ] 可加载指定版本用于分析

### 4.2 人工审核

- [ ] 可为分析结果创建审核记录
- [ ] 支持通过/驳回/退回状态
- [ ] 驳回时必须填写原因
- [ ] 审核记录可追溯（JSON 文件）
- [ ] 可按政策 ID 查询审核历史

---

## 5. 非功能需求

| 需求 | 要求 |
| --- | --- |
| 可追溯性 | 知识库版本、审核记录均不可覆盖 |
| 安全性 | 审核人 ID 必须记录，不信任匿名操作 |
| 可靠性 | 单条审核失败不影响其他记录 |
| 性能 | 单次导入 Excel < 5 秒（100 条规则以内） |

---

## 6. 待确认事项

1. 审核人 ID 来源：固定字符串还是用户登录系统？
2. 知识库 Excel 模板是否提供下载？
3. 审核记录是否允许修改？（建议：不允许，只能新增修正记录）

---

## 7. 完成定义

当且仅当以下条件均满足时，本 Spec 形成完整闭环：

```yaml
definition_of_done:
  - 知识库 Excel 可导入并校验
  - 版本列表可查询
  - 分析流程可加载知识库
  - 审核记录可创建和查询
  - Excel 导出包含审核状态
```
