# 政策融资需求识别系统 P0 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 3 小时内实现人工审核（简化版）并集成到采集分析流程

**Architecture:** 
- 人工审核：`review.py` 负责审核记录创建、查询
- 集成：`pipeline.py` 在分析后创建审核记录

**Tech Stack:** Python 3.11+, JSON 文件存储

**Global Constraints:**
- 审核记录不可覆盖，只能新增
- 审核记录文件格式：`review-{policy_id}-{timestamp}.json`
- 审核驳回原因必须是枚举值之一

---

## Task 1: 人工审核模块（创建、查询、状态管理）

**Files:**
- Create: `src/opportunity_radar/review.py`
- Test: `tests/test_review.py`

**Interfaces:**
- Consumes: `IndustryOpportunity`
- Produces: `ReviewRecord`, `create_review_record()`, `load_review_records()`, `list_review_records()`

### 步骤

- [ ] **Step 1: 实现审核模块**

```python
# src/opportunity_radar/review.py
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, asdict
from datetime import datetime, UTC
from pathlib import Path
from typing import Any, Literal

from opportunity_radar.models import IndustryOpportunity

PROJECT_ROOT = Path(__file__).resolve().parents[2]
REVIEW_DIRECTORY = PROJECT_ROOT / "data" / "reviews"

ReviewStatus = Literal["pending", "approved", "rejected", "returned"]

REJECT_REASONS = [
    "误命中",
    "行业不符",
    "无实际投入",
    "政策失效",
    "证据不足",
    "其他",
]


@dataclass
class ReviewRecord:
    review_id: str
    policy_id: str
    opportunity_index: int
    original_opportunity: dict
    status: ReviewStatus
    reject_reason: str | None
    reviewer_comment: str
    reviewer_id: str
    reviewed_at: datetime
    modified_fields: dict | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ReviewRecord":
        return cls(
            review_id=str(data.get("review_id", "")),
            policy_id=str(data.get("policy_id", "")),
            opportunity_index=int(data.get("opportunity_index", 0)),
            original_opportunity=data.get("original_opportunity", {}),
            status=data.get("status", "pending"),
            reject_reason=data.get("reject_reason"),
            reviewer_comment=str(data.get("reviewer_comment", "")),
            reviewer_id=str(data.get("reviewer_id", "")),
            reviewed_at=datetime.fromisoformat(data["reviewed_at"]) if "reviewed_at" in data else None,
            modified_fields=data.get("modified_fields"),
        )


def create_review_record(
    policy_id: str,
    opportunity: IndustryOpportunity,
    status: ReviewStatus,
    reviewer_id: str,
    comment: str,
    reject_reason: str | None = None,
    opportunity_index: int = 0,
) -> ReviewRecord:
    """Create a review record and save to file."""
    if status == "rejected" and not reject_reason:
        raise ValueError("驳回时必须填写原因")
    if reject_reason and reject_reason not in REJECT_REASONS:
        raise ValueError(f"驳回原因必须是以下之一：{REJECT_REASONS}")

    review_id = f"review-{policy_id}-{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:6]}"

    record = ReviewRecord(
        review_id=review_id,
        policy_id=policy_id,
        opportunity_index=opportunity_index,
        original_opportunity=opportunity.model_dump(mode="json"),
        status=status,
        reject_reason=reject_reason,
        reviewer_comment=comment,
        reviewer_id=reviewer_id,
        reviewed_at=datetime.now(UTC),
        modified_fields=None,
    )

    REVIEW_DIRECTORY.mkdir(parents=True, exist_ok=True)
    path = REVIEW_DIRECTORY / f"{review_id}.json"
    path.write_text(
        json.dumps(record.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return record


def load_review_records(policy_id: str) -> list[ReviewRecord]:
    """Load review records for a specific policy."""
    if not REVIEW_DIRECTORY.exists():
        return []

    records = []
    for path in REVIEW_DIRECTORY.glob(f"review-{policy_id}-*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            records.append(ReviewRecord.from_dict(data))
        except Exception:
            continue

    return sorted(records, key=lambda r: r.reviewed_at)


def list_review_records(
    status: ReviewStatus | None = None,
    reviewer_id: str | None = None,
) -> list[ReviewRecord]:
    """List all review records with optional filters."""
    if not REVIEW_DIRECTORY.exists():
        return []

    records = []
    for path in REVIEW_DIRECTORY.glob("review-*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            record = ReviewRecord.from_dict(data)
            if status and record.status != status:
                continue
            if reviewer_id and record.reviewer_id != reviewer_id:
                continue
            records.append(record)
        except Exception:
            continue

    return sorted(records, key=lambda r: r.reviewed_at, reverse=True)
```

- [ ] **Step 2: 编写测试**

```python
# tests/test_review.py
from opportunity_radar.review import (
    ReviewRecord,
    ReviewStatus,
    REJECT_REASONS,
    create_review_record,
    load_review_records,
    list_review_records,
    REVIEW_DIRECTORY,
)
from opportunity_radar.models import IndustryOpportunity, Evidence


def test_review_record_creation():
    opportunity = IndustryOpportunity(
        section_code="C",
        section_name="制造业",
        division_code="C34",
        division_name="通用设备制造业",
        business_tags=["新能源"],
        confidence=0.9,
        scenarios=["设备采购"],
        evidence=[Evidence(quote="test quote", location="正文字符 1-10")],
        leasing_relevance="高",
        recommended_action="联系企业",
        opening_script="您好",
    )
    record = create_review_record(
        policy_id="policy-001",
        opportunity=opportunity,
        status="pending",
        reviewer_id="reviewer-001",
        comment="待审核",
    )
    assert record.review_id.startswith("review-")
    assert record.status == "pending"
    assert record.reviewer_id == "reviewer-001"


def test_reject_reason_enum():
    assert "误命中" in REJECT_REASONS
    assert "行业不符" in REJECT_REASONS
    assert "无效原因" not in REJECT_REASONS


def test_create_and_load_review_record():
    opportunity = IndustryOpportunity(
        section_code="C",
        section_name="制造业",
        division_code="C34",
        division_name="通用设备制造业",
        business_tags=["新能源"],
        confidence=0.9,
        scenarios=["设备采购"],
        evidence=[Evidence(quote="test quote", location="正文字符 1-10")],
        leasing_relevance="高",
        recommended_action="联系企业",
        opening_script="您好",
    )
    record = create_review_record(
        policy_id="policy-test-001",
        opportunity=opportunity,
        status="pending",
        reviewer_id="reviewer-001",
        comment="待审核",
    )
    records = load_review_records("policy-test-001")
    assert len(records) >= 1
    assert records[-1].review_id == record.review_id


def test_list_review_records_by_status():
    pending_records = list_review_records(status="pending")
    assert isinstance(pending_records, list)
    for r in pending_records:
        assert r.status == "pending"


def test_reject_requires_reason():
    opportunity = IndustryOpportunity(
        section_code="C",
        section_name="制造业",
        division_code="C34",
        division_name="通用设备制造业",
        business_tags=["新能源"],
        confidence=0.9,
        scenarios=["设备采购"],
        evidence=[Evidence(quote="test quote", location="正文字符 1-10")],
        leasing_relevance="高",
        recommended_action="联系企业",
        opening_script="您好",
    )
    try:
        create_review_record(
            policy_id="policy-002",
            opportunity=opportunity,
            status="rejected",
            reviewer_id="reviewer-001",
            comment="驳回",
            reject_reason=None,
        )
        assert False, "Should have raised ValueError"
    except ValueError as e:
        assert "驳回时必须填写原因" in str(e)
```

- [ ] **Step 3: 运行测试**

```bash
cd /Users/zhouteng/Documents/workspace/AI-opportunity-radar
source .venv/bin/activate
pytest tests/test_review.py -v
```

- [ ] **Step 4: 提交**

```bash
git add src/opportunity_radar/review.py tests/test_review.py
git commit -m "feat(review): add review record CRUD with status management"
```

---

## Task 2: 集成审核记录到分析流程

**Files:**
- Modify: `src/opportunity_radar/pipeline.py`

**Interfaces:**
- Consumes: `create_review_record()`
- Produces: 每个分析结果自动创建审核记录

### 步骤

- [ ] **Step 1: 修改 pipeline.py**

在 `src/opportunity_radar/pipeline.py` 文件顶部添加导入：
```python
from opportunity_radar.review import create_review_record
```

在 `run_pipeline` 函数中，找到分析循环部分（约第 314-333 行），修改为：

```python
try:
    analysis = analyzer.analyze(document, valid_codes, business_tags)
    analyzed_at = datetime.now(UTC)
    if analysis.is_benefit_policy and not analysis.opportunities:
        rows.append(_benefit_observation_row(document, analysis, analyzed_at))
    for opportunity_index, opportunity in enumerate(analysis.opportunities):
        # 创建审核记录
        review = create_review_record(
            policy_id=document.policy_id,
            opportunity=opportunity,
            status="pending",
            reviewer_id="system",
            comment="AI 自动分析结果，待人工审核",
            opportunity_index=opportunity_index,
        )
        
        quality = evaluate(
            document,
            opportunity,
            reference_date=config.end_date,
        )
        rows.append(
            _opportunity_row(
                document,
                analysis,
                opportunity,
                quality,
                analyzed_at,
            )
        )
except Exception as error:
    # ... 现有错误处理逻辑不变
```

- [ ] **Step 2: 运行现有测试验证不破坏**

```bash
pytest tests/test_pipeline.py -v
```

- [ ] **Step 3: 提交**

```bash
git add src/opportunity_radar/pipeline.py
git commit -m "feat(pipeline): create review records after analysis"
```

---

## Task 3: 审核记录查询接口（Web 控制台）

**Files:**
- Modify: `src/opportunity_radar/ui_server.py`
- Modify: `src/opportunity_radar/ui_static/app.js`

**Interfaces:**
- Consumes: `list_review_records()`, `load_review_records()`
- Produces: Web API 和页面展示审核记录

### 步骤

- [ ] **Step 1: 添加 API 端点**

在 `src/opportunity_radar/ui_server.py` 中添加：

```python
# 在文件顶部添加导入
from opportunity_radar.review import list_review_records, load_review_records

# 在 do_GET 方法中添加 API 端点（约第 676 行后）
elif parsed.path == "/api/reviews":
    status = query.get("status", [None])[0]
    self._send_json([r.to_dict() for r in list_review_records(status=status)])
elif parsed.path == "/api/reviews/policy":
    policy_id = query.get("policy_id", [""])[0]
    self._send_json([r.to_dict() for r in load_review_records(policy_id)])
```

- [ ] **Step 2: 修改 UI 页面**

在 `src/opportunity_radar/ui_static/index.html` 中添加审核页面（约第 307 行，`page-results` 之后）：

```html
<section id="page-review" class="page">
  <div class="toolbar panel">
    <label>
      审核状态
      <select id="review-status-filter">
        <option value="">全部</option>
        <option value="pending">待审核</option>
        <option value="approved">已通过</option>
        <option value="rejected">已驳回</option>
        <option value="returned">已退回</option>
      </select>
    </label>
    <button id="filter-reviews" class="secondary-button">筛选</button>
  </div>
  <div id="review-stats" class="inline-stats"></div>
  <div class="table-shell">
    <table>
      <thead>
        <tr>
          <th>审核时间</th>
          <th>政策 ID</th>
          <th>状态</th>
          <th>审核人</th>
          <th>意见</th>
          <th>驳回原因</th>
        </tr>
      </thead>
      <tbody id="review-rows"></tbody>
    </table>
  </div>
  <div id="review-pagination" class="pagination"></div>
</section>
```

在导航中添加审核按钮（约第 42 行后）：
```html
<button class="nav-item" data-page="review">
  <b>06</b><span>人工审核</span>
</button>
```

- [ ] **Step 3: 添加前端 JS 逻辑**

在 `src/opportunity_radar/ui_static/app.js` 中添加：

```javascript
// 添加导航处理
case 'review':
  await loadReviews();
  break;

// 添加 loadReviews 函数
async function loadReviews() {
  const status = document.getElementById('review-status-filter').value;
  const res = await fetch(`/api/reviews?status=${status}`);
  const reviews = await res.json();
  
  document.getElementById('review-stats').innerHTML = `共 ${reviews.length} 条审核记录`;
  
  const tbody = document.getElementById('review-rows');
  tbody.innerHTML = reviews.map(r => `
    <tr>
      <td>${new Date(r.reviewed_at).toLocaleString('zh-CN')}</td>
      <td>${r.policy_id}</td>
      <td>${r.status}</td>
      <td>${r.reviewer_id}</td>
      <td>${r.reviewer_comment || '-'}</td>
      <td>${r.reject_reason || '-'}</td>
    </tr>
  `).join('');
}

// 添加筛选事件绑定
document.getElementById('filter-reviews')?.addEventListener('click', loadReviews);
```

- [ ] **Step 4: 提交**

```bash
git add src/opportunity_radar/ui_server.py src/opportunity_radar/ui_static/
git commit -m "feat(ui): add review records page and API"
```

---

## 计划自审查

**1. Spec 覆盖检查：**

| Spec 要求 | 实现 Task |
| --- | --- |
| 审核记录创建 | Task 1 |
| 通过/驳回/退回状态 | Task 1 |
| 驳回原因必填 | Task 1 |
| 审核记录可追溯 | Task 1 |
| 集成到采集流程 | Task 2 |
| Web 页面展示 | Task 3 |

**2. 无占位符检查：** ✅ 所有步骤都有具体代码

**3. 类型一致性检查：** ✅ `ReviewStatus` 在整个计划中保持一致

---

## 执行选择

计划已保存到 `docs/superpowers/plans/2026-08-01-policy-financing-p0-implementation.md`

**两种执行方式可选：**

**1. Subagent-Driven（推荐）** - 每个 Task 由独立子代理执行

**2. Inline Execution** - 在当前会话中按顺序执行 Tasks

**选择哪种方式？**
