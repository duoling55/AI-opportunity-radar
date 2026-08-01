# 政策融资需求识别系统 P0 缺失功能实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 3 小时内实现知识库管理和人工审核，并集成到采集分析流程

**Architecture:** 
- 知识库：`knowledge.py` 负责 Excel 导入、校验、版本保存/加载
- 人工审核：`review.py` 负责审核记录创建、查询
- 集成：`pipeline.py` 加载知识库、创建审核记录

**Tech Stack:** Python 3.11+, openpyxl, JSON 文件存储

**Global Constraints:**
- 审核记录不可覆盖，只能新增
- 知识库版本文件名：`knowledge-{version}.json`
- 审核记录文件格式：`review-{policy_id}-{timestamp}.json`
- Excel 校验失败必须返回具体错误行号和原因
- 审核驳回原因必须是枚举值之一

---

## Task 1: 知识库管理模块（Excel 导入、校验、版本化）

**Files:**
- Create: `src/opportunity_radar/knowledge.py`
- Test: `tests/test_knowledge.py`

**Interfaces:**
- Consumes: `openpyxl.load_workbook`
- Produces: `KnowledgeRule`, `KnowledgeBase`, `import_knowledge_base()`, `load_knowledge_base()`, `list_knowledge_versions()`

### 步骤

- [ ] **Step 1: 实现知识模块（数据模型 + Excel 校验 + 版本管理）**

```python
# src/opportunity_radar/knowledge.py
from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from datetime import datetime, UTC
from pathlib import Path
from typing import Any

from openpyxl import load_workbook

PROJECT_ROOT = Path(__file__).resolve().parents[2]
KNOWLEDGE_DIRECTORY = PROJECT_ROOT / "data" / "knowledge"


@dataclass
class KnowledgeRule:
    rule_id: str
    policy_trigger_type: str
    keywords_or_typical_phrases: list[str]
    enterprise_behavior: str
    primary_financing_need: str
    suitable_financial_leasing_product: str
    applicable_industry_examples: list[str]
    signal_strength: str
    identification_notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "KnowledgeRule":
        return cls(
            rule_id=str(data.get("rule_id", "")).strip(),
            policy_trigger_type=str(data.get("policy_trigger_type", "")).strip(),
            keywords_or_typical_phrases=[
                str(k).strip() for k in data.get("keywords_or_typical_phrases", []) if str(k).strip()
            ],
            enterprise_behavior=str(data.get("enterprise_behavior", "")).strip(),
            primary_financing_need=str(data.get("primary_financing_need", "")).strip(),
            suitable_financial_leasing_product=str(data.get("suitable_financial_leasing_product", "")).strip(),
            applicable_industry_examples=[
                str(i).strip() for i in data.get("applicable_industry_examples", []) if str(i).strip()
            ],
            signal_strength=str(data.get("signal_strength", "")).strip(),
            identification_notes=str(data.get("identification_notes", "")).strip(),
        )


@dataclass
class KnowledgeBase:
    version: str
    rules: list[KnowledgeRule]
    created_at: datetime
    created_by: str

    def __init__(
        self,
        version: str,
        rules: list[KnowledgeRule],
        created_at: datetime | None = None,
        created_by: str = "system",
    ) -> None:
        self.version = version
        self.rules = rules
        self.created_at = created_at or datetime.now(UTC)
        self.created_by = created_by

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "rules": [rule.to_dict() for rule in self.rules],
            "created_at": self.created_at.isoformat(),
            "created_by": self.created_by,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "KnowledgeBase":
        return cls(
            version=str(data.get("version", "unknown")),
            rules=[KnowledgeRule.from_dict(r) for r in data.get("rules", [])],
            created_at=datetime.fromisoformat(data["created_at"]) if "created_at" in data else None,
            created_by=str(data.get("created_by", "system")),
        )


def validate_excel_knowledge(excel_path: Path) -> tuple[list[dict[str, Any]], list[str]]:
    """Validate Excel knowledge base file and return rules and errors."""
    errors: list[str] = []
    rules: list[dict[str, Any]] = []

    try:
        workbook = load_workbook(excel_path, read_only=True, data_only=True)
    except Exception as e:
        return [], [f"Excel 文件无法打开：{e}"]

    sheet_names = workbook.sheetnames
    if not sheet_names:
        return [], ["Excel 文件没有工作表"]

    sheet = workbook[sheet_names[0]]
    rows = list(sheet.iter_rows(values_only=True))

    if not rows:
        return [], ["Excel 文件为空"]

    headers = [str(h or "").strip() for h in next(rows, ())]
    required_headers = {
        "rule_id",
        "policy_trigger_type",
        "keywords_or_typical_phrases",
        "enterprise_behavior",
        "primary_financing_need",
        "suitable_financial_leasing_product",
        "applicable_industry_examples",
        "signal_strength",
    }
    header_set = {h.lower().replace(" ", "_") for h in headers}
    missing = required_headers - header_set
    if missing:
        return [], [f"缺少必需列：{', '.join(missing)}"]

    header_map = {h.lower().replace(" ", "_"): i for i, h in enumerate(headers)}

    for row_num, row in enumerate(rows, start=2):
        if not any(cell for cell in row):
            continue

        try:
            rule_data = {
                "rule_id": str(row[header_map.get("rule_id", 0)] or "").strip(),
                "policy_trigger_type": str(row[header_map.get("policy_trigger_type", 1)] or "").strip(),
                "keywords_or_typical_phrases": [
                    str(k).strip()
                    for k in str(row[header_map.get("keywords_or_typical_phrases", 2)] or "").split(",")
                    if str(k).strip()
                ],
                "enterprise_behavior": str(row[header_map.get("enterprise_behavior", 3)] or "").strip(),
                "primary_financing_need": str(row[header_map.get("primary_financing_need", 4)] or "").strip(),
                "suitable_financial_leasing_product": str(
                    row[header_map.get("suitable_financial_leasing_product", 5)] or ""
                ).strip(),
                "applicable_industry_examples": [
                    str(i).strip()
                    for i in str(row[header_map.get("applicable_industry_examples", 6)] or "").split(",")
                    if str(i).strip()
                ],
                "signal_strength": str(row[header_map.get("signal_strength", 7)] or "").strip(),
                "identification_notes": str(row[header_map.get("identification_notes", 8)] or "").strip(),
            }

            if not rule_data["rule_id"]:
                errors.append(f"第{row_num}行：rule_id 为空")
                continue
            if not rule_data["policy_trigger_type"]:
                errors.append(f"第{row_num}行：policy_trigger_type 为空")
                continue
            if not rule_data["keywords_or_typical_phrases"]:
                errors.append(f"第{row_num}行：keywords_or_typical_phrases 为空")
                continue
            if rule_data["signal_strength"] not in {"很强", "中等", "弱"}:
                errors.append(f"第{row_num}行：signal_strength 必须是'很强'、'中等'或'弱'")
                continue

            rules.append(rule_data)

        except Exception as e:
            errors.append(f"第{row_num}行解析失败：{e}")

    return rules, errors


def import_knowledge_base(
    excel_path: Path,
    version: str,
    created_by: str = "system",
) -> KnowledgeBase:
    """Import Excel knowledge base and save as JSON version."""
    rules_data, errors = validate_excel_knowledge(excel_path)
    if errors:
        raise ValueError(f"Excel 校验失败：{'; '.join(errors)}")

    rules = [KnowledgeRule.from_dict(r) for r in rules_data]
    kb = KnowledgeBase(
        version=version,
        rules=rules,
        created_at=datetime.now(UTC),
        created_by=created_by,
    )

    KNOWLEDGE_DIRECTORY.mkdir(parents=True, exist_ok=True)
    path = KNOWLEDGE_DIRECTORY / f"knowledge-{version}.json"
    path.write_text(
        json.dumps(kb.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return kb


def load_knowledge_base(version: str = "latest") -> KnowledgeBase | None:
    """Load knowledge base from file."""
    if version == "latest":
        files = sorted(
            KNOWLEDGE_DIRECTORY.glob("knowledge-*.json"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        if not files:
            return None
        version = files[0].stem.replace("knowledge-", "")

    path = KNOWLEDGE_DIRECTORY / f"knowledge-{version}.json"
    if not path.exists():
        return None

    return KnowledgeBase.from_dict(json.loads(path.read_text(encoding="utf-8")))


def list_knowledge_versions() -> list[dict[str, Any]]:
    """List all available knowledge base versions."""
    if not KNOWLEDGE_DIRECTORY.exists():
        return []

    versions = []
    for path in sorted(
        KNOWLEDGE_DIRECTORY.glob("knowledge-*.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    ):
        try:
            kb = KnowledgeBase.from_dict(json.loads(path.read_text(encoding="utf-8")))
            versions.append(
                {
                    "version": kb.version,
                    "created_at": kb.created_at.isoformat(),
                    "created_by": kb.created_by,
                    "rule_count": len(kb.rules),
                    "file": path.name,
                }
            )
        except Exception:
            continue

    return versions
```

- [ ] **Step 2: 编写测试**

```python
# tests/test_knowledge.py
import tempfile
from pathlib import Path
from openpyxl import Workbook
from datetime import UTC, datetime

from opportunity_radar.knowledge import (
    KnowledgeRule,
    KnowledgeBase,
    validate_excel_knowledge,
    import_knowledge_base,
    load_knowledge_base,
    list_knowledge_versions,
    KNOWLEDGE_DIRECTORY,
)


def create_test_excel() -> Path:
    wb = Workbook()
    ws = wb.active
    headers = [
        "rule_id", "policy_trigger_type", "keywords_or_typical_phrases",
        "enterprise_behavior", "primary_financing_need",
        "suitable_financial_leasing_product", "applicable_industry_examples",
        "signal_strength", "identification_notes"
    ]
    ws.append(headers)
    ws.append([
        "test-001", "设备更新", "设备更新，技改",
        "采购新设备", "设备融资", "直租",
        "制造业", "很强", "备注"
    ])
    f = tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False)
    wb.save(f.name)
    return Path(f.name)


def test_knowledge_rule_creation():
    rule = KnowledgeRule(
        rule_id="test-001",
        policy_trigger_type="设备更新",
        keywords_or_typical_phrases=["设备更新", "技改"],
        enterprise_behavior="采购新设备",
        primary_financing_need="设备融资",
        suitable_financial_leasing_product="直租",
        applicable_industry_examples=["制造业"],
        signal_strength="很强",
    )
    assert rule.rule_id == "test-001"
    assert rule.signal_strength == "很强"


def test_validate_valid_excel():
    f = create_test_excel()
    try:
        rules, errors = validate_excel_knowledge(f)
        assert len(rules) == 1
        assert len(errors) == 0
        assert rules[0]["rule_id"] == "test-001"
    finally:
        f.unlink()


def test_validate_missing_columns():
    wb = Workbook()
    ws = wb.active
    ws.append(["rule_id", "policy_trigger_type"])
    f = tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False)
    wb.save(f.name)
    try:
        rules, errors = validate_excel_knowledge(Path(f.name))
        assert len(rules) == 0
        assert len(errors) > 0
        assert "缺少必需列" in errors[0]
    finally:
        f.unlink()


def test_import_and_load_knowledge_base():
    f = create_test_excel()
    try:
        kb = import_knowledge_base(f, version="v2026-08-01-test", created_by="test")
        assert kb.version == "v2026-08-01-test"
        assert len(kb.rules) == 1

        loaded = load_knowledge_base("v2026-08-01-test")
        assert loaded is not None
        assert loaded.version == kb.version
    finally:
        f.unlink()
        test_file = KNOWLEDGE_DIRECTORY / "knowledge-v2026-08-01-test.json"
        if test_file.exists():
            test_file.unlink()


def test_list_knowledge_versions():
    versions = list_knowledge_versions()
    assert isinstance(versions, list)
```

- [ ] **Step 3: 运行测试**

```bash
cd /Users/zhouteng/Documents/workspace/AI-opportunity-radar
source .venv/bin/activate
pytest tests/test_knowledge.py -v
```

- [ ] **Step 4: 提交**

```bash
git add src/opportunity_radar/knowledge.py tests/test_knowledge.py
git commit -m "feat(knowledge): add Excel import, validation, and versioning"
```

---

## Task 2: 人工审核模块（创建、查询、状态管理）

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
    assert record.review_id is not None

    records = load_review_records("policy-test-001")
    assert len(records) >= 1
    assert records[-1].review_id == record.review_id


def test_list_review_records_by_status():
    all_records = list_review_records()
    assert isinstance(all_records, list)

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
pytest tests/test_review.py -v
```

- [ ] **Step 4: 提交**

```bash
git add src/opportunity_radar/review.py tests/test_review.py
git commit -m "feat(review): add review record CRUD with status management"
```

---

## Task 3: 集成到采集分析流程

**Files:**
- Modify: `src/opportunity_radar/pipeline.py`

**Interfaces:**
- Consumes: `load_knowledge_base()`, `create_review_record()`
- Produces: 采集分析流程自动加载知识库、创建审核记录

### 步骤

- [ ] **Step 1: 修改 pipeline.py**

```python
# src/opportunity_radar/pipeline.py
# 在文件顶部添加导入
from opportunity_radar.knowledge import load_knowledge_base
from opportunity_radar.review import create_review_record

# 在 run_pipeline 函数中，找到分析循环部分（约第 291 行）
# 修改为：

for document_index, (document, dedupe_key) in enumerate(selected_documents, start=1):
    if (
        not config.force_reanalyze
        and not store.is_changed(document.policy_id, document.content_hash, dedupe_key)
    ):
        report = _increment(report, "skipped")
        LOGGER.info(
            "政策内容未变化，跳过分析 policy=%d/%d policy_id=%s title=%r",
            document_index,
            len(selected_documents),
            document.policy_id,
            document.title,
        )
        continue
    report = _increment(report, "changed")
    analysis_started_at = perf_counter()
    LOGGER.info(
        "开始分析政策 policy=%d/%d policy_id=%s title=%r",
        document_index,
        len(selected_documents),
        document.policy_id,
        document.title,
    )
    try:
        analysis = analyzer.analyze(document, valid_codes, business_tags)
        analyzed_at = datetime.now(UTC)
        
        # 加载知识库（简化版：只加载记录日志，不用于碰撞）
        knowledge_base = load_knowledge_base(version="latest")
        if knowledge_base:
            LOGGER.info(
                "加载知识库 version=%s rules=%d",
                knowledge_base.version,
                len(knowledge_base.rules),
            )
        
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
        report = _increment(report, "analysis_failures")
        LOGGER.exception(
            "政策分析失败 policy=%d/%d policy_id=%s title=%r "
            "elapsed_seconds=%.2f",
            document_index,
            len(selected_documents),
            document.policy_id,
            document.title,
            perf_counter() - analysis_started_at,
        )
        rows.append(
            _analysis_failure_observation_row(
                document,
                error,
                datetime.now(UTC),
            )
        )
        continue

    store.record_success(document.policy_id, document.content_hash, dedupe_key)
```

- [ ] **Step 2: 运行现有测试验证不破坏**

```bash
pytest tests/test_pipeline.py -v
```

- [ ] **Step 3: 提交**

```bash
git add src/opportunity_radar/pipeline.py
git commit -m "feat(pipeline): integrate knowledge base loading and review record creation"
```

---

## 计划自审查

**1. Spec 覆盖检查：**

| Spec 要求 | 实现 Task |
| --- | --- |
| Excel 导入校验 | Task 1 |
| 版本保存与列表 | Task 1 |
| 加载指定版本 | Task 1 |
| 审核记录创建 | Task 2 |
| 通过/驳回/退回状态 | Task 2 |
| 驳回原因必填 | Task 2 |
| 审核记录可追溯 | Task 2 |
| 集成到采集流程 | Task 3 |

**2. 无占位符检查：** ✅ 所有步骤都有具体代码

**3. 类型一致性检查：** ✅ `ReviewStatus` 在整个计划中保持一致

---

## 执行选择

计划已保存到 `docs/superpowers/plans/2026-08-01-policy-financing-p0-implementation.md`

**两种执行方式可选：**

**1. Subagent-Driven（推荐）** - 每个 Task 由独立子代理执行，Task 间进行两阶段审查

**2. Inline Execution** - 在当前会话中按顺序执行 Tasks

**选择哪种方式？**
