# 合规来源登记与运行前校验 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将国务院政策文件库、浙江·数据开放和江苏惠企专区登记为默认禁用的合规候选来源，并在任何网络请求前阻断未核验来源。

**Architecture:** 新增独立的机器可读合规台账和小型领域模块，避免把合规字段混入现有抓取适配器配置。CLI 先解析台账、校验来源状态和核验期限，再构造 HTTP 来源适配器或初始化模型；只有 `verified` 且 `enabled=true` 的来源可进入既有采集管道。

**Tech Stack:** Python 3.11、`dataclasses`、JSON、argparse、pytest、Ruff。

## Global Constraints

- 首批三项来源初始均为 `candidate`、`enabled=false`，不得自动采集。
- 开放条款、注册、认证、限频、数据集范围或字段许可任一未确认时，来源不得启用。
- 仅 `verified`、`enabled=true`、未到复核日期、登记授权证据和明确限频的来源可运行。
- CLI 必须在创建来源适配器、读取模型密钥和发起任何网络请求之前拒绝不合规来源。
- 不保存 API Key、Cookie 或账号密码；不得实现指纹伪装、验证码绕过、代理轮换或访问控制规避。
- 未公开的规则必须记录为 `unknown`，不得用推测值替代。

---

## File Structure

- Create: `config/compliance_sources.json` — 首批候选来源的机器可读合规台账。
- Create: `src/opportunity_radar/compliance.py` — 台账数据模型、加载器与可运行性判定。
- Create: `tests/test_compliance.py` — 合规台账加载和状态校验的单元测试。
- Modify: `src/opportunity_radar/cli.py` — 在构建适配器和读取 LLM 配置前执行来源选择校验。
- Modify: `tests/test_pipeline.py` — CLI 显式选择候选、未登记和已核验来源的行为测试。
- Modify: `README.md` — 更新运行说明，说明默认不会自动运行候选来源及启用步骤。
- Modify: `docs/operations/policy-source-smoke-check.md` — 加入合规核验前置检查。

### Task 1: 建立合规台账领域模型和候选来源配置

**Files:**
- Create: `src/opportunity_radar/compliance.py`
- Create: `config/compliance_sources.json`
- Create: `tests/test_compliance.py`

**Interfaces:**
- Produces: `ComplianceSource` frozen dataclass with `source_id`, `phase`, `enabled`, `rate_limit`, `authorization`, `evidence_url`, `verified_at`, `review_due_at`, `owner` and `available_fields`.
- Produces: `load_compliance_sources(path: Path) -> dict[str, ComplianceSource]`.
- Produces: `ComplianceSource.blocking_reason(today: date) -> str | None`; `None` means the source is eligible to run.

- [ ] **Step 1: Write failing tests for the initial registry and run eligibility**

Create `tests/test_compliance.py`:

```python
from datetime import date
from pathlib import Path

from opportunity_radar.compliance import ComplianceSource, load_compliance_sources


def test_initial_registry_contains_only_disabled_candidates() -> None:
    sources = load_compliance_sources(Path("config/compliance_sources.json"))

    assert set(sources) == {
        "state_council_policy_library",
        "zhejiang_open_data",
        "jiangsu_benefit_policy",
    }
    assert all(source.phase == "candidate" for source in sources.values())
    assert all(source.enabled is False for source in sources.values())
    assert all(source.rate_limit == "unknown" for source in sources.values())
    assert all(source.owner == "unassigned" for source in sources.values())


def test_candidate_source_is_blocked_before_any_adapter_is_built() -> None:
    source = ComplianceSource(
        source_id="candidate",
        display_name="候选来源",
        phase="candidate",
        enabled=False,
        rate_limit="unknown",
        authorization="unknown",
        evidence_url="https://example.gov.cn/evidence",
        verified_at=None,
        review_due_at=date(2026, 10, 27),
        owner="unassigned",
        available_fields=("标题",),
    )

    assert source.blocking_reason(date(2026, 7, 29)) == "phase=candidate"


def test_verified_source_requires_current_evidence_limit_authorization_and_owner() -> None:
    source = ComplianceSource(
        source_id="verified",
        display_name="已核验来源",
        phase="verified",
        enabled=True,
        rate_limit="1 request per 5 seconds",
        authorization="written_permission",
        evidence_url="https://example.gov.cn/permission",
        verified_at=date(2026, 7, 1),
        review_due_at=date(2026, 10, 1),
        owner="policy-ops",
        available_fields=("标题",),
    )

    assert source.blocking_reason(date(2026, 7, 29)) is None
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_compliance.py -q`

Expected: FAIL during test collection with `ModuleNotFoundError: No module named 'opportunity_radar.compliance'`.

- [ ] **Step 3: Implement the immutable model, loader and fail-closed predicate**

Create `src/opportunity_radar/compliance.py` with these exact core rules:

```python
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path


@dataclass(frozen=True)
class ComplianceSource:
    source_id: str
    display_name: str
    phase: str
    enabled: bool
    rate_limit: str
    authorization: str
    evidence_url: str
    verified_at: date | None
    review_due_at: date | None
    owner: str
    available_fields: tuple[str, ...]

    def blocking_reason(self, today: date) -> str | None:
        if self.phase != "verified":
            return f"phase={self.phase}"
        if not self.enabled:
            return "enabled=false"
        if self.rate_limit == "unknown":
            return "rate_limit=unknown"
        if self.authorization in {"unknown", "none"}:
            return f"authorization={self.authorization}"
        if not self.evidence_url:
            return "evidence_url=missing"
        if self.verified_at is None:
            return "verified_at=missing"
        if self.review_due_at is None or self.review_due_at <= today:
            return "review_due_at=expired"
        if self.owner == "unassigned":
            return "owner=unassigned"
        return None


def load_compliance_sources(path: Path) -> dict[str, ComplianceSource]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return {
        item["source_id"]: ComplianceSource(
            source_id=item["source_id"],
            display_name=item["display_name"],
            phase=item["phase"],
            enabled=item["enabled"],
            rate_limit=item["rate_limit"],
            authorization=item["authorization"],
            evidence_url=item["evidence_url"],
            verified_at=(date.fromisoformat(item["verified_at"]) if item["verified_at"] else None),
            review_due_at=date.fromisoformat(item["review_due_at"]),
            owner=item["owner"],
            available_fields=tuple(item["available_fields"]),
        )
        for item in payload
    }
```

Create `config/compliance_sources.json` with the three source IDs in the test. For every record set `phase` to `"candidate"`, `enabled` to `false`, `rate_limit` and `authorization` to `"unknown"`, `verified_at` to `null`, `owner` to `"unassigned"`, and `review_due_at` to `"2026-10-27"`. Preserve the official URLs, terms summary, registration status, available fields, evidence URL and enablement conditions from the approved design specification as additional JSON properties.

- [ ] **Step 4: Run focused tests and lint**

Run:

```bash
.venv/bin/python -m pytest tests/test_compliance.py -q
.venv/bin/ruff check src/opportunity_radar/compliance.py tests/test_compliance.py
```

Expected: both commands exit 0.

- [ ] **Step 5: Commit the independently testable registry model**

```bash
git add config/compliance_sources.json src/opportunity_radar/compliance.py tests/test_compliance.py
git commit -m "feat: add fail-closed compliance source registry"
```

### Task 2: 在 CLI 阻断候选、未登记和过期来源

**Files:**
- Modify: `src/opportunity_radar/cli.py`
- Modify: `tests/test_pipeline.py`

**Interfaces:**
- Consumes: `load_compliance_sources(Path) -> dict[str, ComplianceSource]` and `ComplianceSource.blocking_reason(today) -> str | None` from Task 1.
- Produces: `_select_compliant_sources(requested: tuple[str, ...] | None, configured: dict[str, SourceConfig], compliance: dict[str, ComplianceSource], today: date) -> tuple[str, ...]`.
- Produces: CLI errors before `build_sources`, `DocumentRetriever`, analyzer construction or pipeline invocation.

- [ ] **Step 1: Write failing CLI tests for pre-network blocking**

Append to `tests/test_pipeline.py`:

```python
def test_cli_rejects_candidate_before_building_sources(
    monkeypatch: Any, capsys: pytest.CaptureFixture[str]
) -> None:
    from opportunity_radar import cli

    candidate = ComplianceSource(
        "state_council_policy_library", "国务院政策文件库", "candidate", False,
        "unknown", "unknown", "https://example.gov.cn/evidence", None,
        date(2026, 10, 27), "unassigned", ("标题",),
    )
    monkeypatch.setattr(cli, "load_sources", lambda path: {})
    monkeypatch.setattr(cli, "load_compliance_sources", lambda path: {candidate.source_id: candidate})
    monkeypatch.setattr(cli, "build_sources", lambda _: (_ for _ in ()).throw(AssertionError("no network")))

    with pytest.raises(SystemExit):
        cli.main(["run", "--sources", "state_council_policy_library"])

    assert "not eligible: state_council_policy_library (phase=candidate)" in capsys.readouterr().err


def test_cli_default_selects_only_verified_enabled_registered_sources(monkeypatch: Any, tmp_path: Path) -> None:
    from opportunity_radar import cli

    configured = {
        "verified": SourceConfig("verified", "已核验", "全国", ("https://verified.example.gov.cn",), ("verified.example.gov.cn",)),
        "legacy": SourceConfig("legacy", "未登记", "全国", ("https://legacy.example.gov.cn",), ("legacy.example.gov.cn",)),
    }
    verified = ComplianceSource(
        "verified", "已核验", "verified", True, "1 request per 5 seconds",
        "written_permission", "https://verified.example.gov.cn/permission", date(2026, 7, 1),
        date(2026, 10, 1), "policy-ops", ("标题",),
    )
    captured: dict[str, object] = {}
    monkeypatch.setattr(cli, "load_sources", lambda path: configured)
    monkeypatch.setattr(cli, "load_compliance_sources", lambda path: {"verified": verified})
    monkeypatch.setattr(cli, "build_sources", lambda selected: captured.setdefault("selected", tuple(selected)) or {"verified": object()})
    monkeypatch.setattr(cli, "load_industry_codes", lambda path: {"C": "制造业", "C34": "通用设备制造业"})
    monkeypatch.setattr(cli, "OpenAICompatibleAnalyzer", lambda *args: object())
    monkeypatch.setattr(cli, "run_pipeline", lambda *args: (tmp_path / "result.xlsx", tmp_path / "report.json"))
    monkeypatch.setenv("OPPORTUNITY_RADAR_LLM_API_KEY", "test-key")
    monkeypatch.setenv("OPPORTUNITY_RADAR_LLM_MODEL", "test-model")

    cli.main(["run"])

    assert captured["selected"] == ("verified",)
```

Add `ComplianceSource` to the imports at the top of this test file.

- [ ] **Step 2: Run the targeted CLI tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_pipeline.py -k "candidate_before or default_selects_only_verified" -q`

Expected: FAIL because `cli` does not yet load or enforce the compliance registry.

- [ ] **Step 3: Implement selection before any side-effectful construction**

In `src/opportunity_radar/cli.py`, import `datetime` and `UTC`, plus `load_compliance_sources`. Add `_select_compliant_sources`:

```python
def _select_compliant_sources(
    requested: tuple[str, ...] | None,
    configured: dict[str, SourceConfig],
    compliance: dict[str, ComplianceSource],
    today: date,
) -> tuple[str, ...]:
    requested_ids = requested or tuple(
        source_id
        for source_id, source in configured.items()
        if source.enabled and source_id in compliance
    )
    problems: list[str] = []
    selected: list[str] = []
    for source_id in requested_ids:
        if source_id not in compliance:
            problems.append(f"{source_id} (not compliance-registered)")
            continue
        reason = compliance[source_id].blocking_reason(today)
        if reason:
            problems.append(f"{source_id} ({reason})")
            continue
        if source_id not in configured:
            problems.append(f"{source_id} (no adapter configured)")
            continue
        if not configured[source_id].enabled:
            problems.append(f"{source_id} (adapter enabled=false)")
            continue
        selected.append(source_id)
    if problems:
        raise ValueError("not eligible: " + ", ".join(problems))
    if not selected:
        raise ValueError("no verified enabled compliance source is configured")
    return tuple(selected)
```

Load `config/compliance_sources.json` immediately after `config/sources.json`; call this helper with `datetime.now(UTC).date()`. Convert its `ValueError` to `parser.error(str(error))`. Delete the existing independent `unknown_sources`, `disabled_sources` and empty-source branches, since the helper supersedes them. Invoke `build_sources` only after the helper returns successfully.

Fix the `captured.setdefault` lambda in the test if necessary by replacing it with a named `fake_build_sources` function that returns `{"verified": object()}`.

- [ ] **Step 4: Run focused tests and the full suite**

Run:

```bash
.venv/bin/python -m pytest tests/test_pipeline.py -k "candidate_before or default_selects_only_verified or explicitly_selected_disabled" -q
.venv/bin/python -m pytest -q
.venv/bin/ruff check src tests scripts
```

Expected: all commands exit 0; the explicit disabled-source test assertion must be updated to expect `not compliance-registered` unless it is supplied a verified compliance record.

- [ ] **Step 5: Commit the CLI guard**

```bash
git add src/opportunity_radar/cli.py tests/test_pipeline.py
git commit -m "feat: block unverified policy sources before collection"
```

### Task 3: 更新操作说明并验证候选来源不会触网

**Files:**
- Modify: `README.md`
- Modify: `docs/operations/policy-source-smoke-check.md`
- Modify: `tests/test_config.py`

**Interfaces:**
- Consumes: `config/compliance_sources.json` from Task 1 and CLI errors from Task 2.
- Produces: 用户可执行的核验、启用、回退和安全冒烟检查流程。

- [ ] **Step 1: Write the failing documentation/configuration assertion**

Append to `tests/test_config.py`:

```python
from opportunity_radar.compliance import load_compliance_sources


def test_candidate_sources_are_not_present_in_automatic_source_config() -> None:
    automatic = load_sources(Path("config/sources.json"))
    candidates = load_compliance_sources(Path("config/compliance_sources.json"))

    assert not (set(automatic) & set(candidates))
```

- [ ] **Step 2: Run the test to verify it passes as a registry separation check**

Run: `.venv/bin/python -m pytest tests/test_config.py::test_candidate_sources_are_not_present_in_automatic_source_config -q`

Expected: PASS. This is an intentional configuration invariant: candidates have no active adapters yet.

- [ ] **Step 3: Update the two operator-facing documents**

In `README.md`, replace the existing “all six configured public policy sources” wording with:

```markdown
## 合规来源开关

`config/compliance_sources.json` 是自动访问的前置台账。候选来源默认
`candidate` 和 `enabled=false`；CLI 会在读取模型密钥或发起网络请求前拒绝它们。
只有完成平台注册/API 或书面授权、记录官方限频和证据链接，并将来源更新为
`verified` 与 `enabled=true` 后，才可配置适配器并运行。

无 API 或授权尚未完成的政策，使用人工导入官方链接或 PDF 的方式处理；不得通过
浏览器指纹、验证码绕过或代理轮换访问来源。
```

In `docs/operations/policy-source-smoke-check.md`, add this first checklist item:

```markdown
1. 在 `config/compliance_sources.json` 确认来源为 `verified`、`enabled=true`，
   `verified_at` 未空、`review_due_at` 未过期、`rate_limit` 非 `unknown`，并已保存
   `evidence_url`、`authorization` 和 `owner`。任何一项不满足时停止，不执行命令。
```

- [ ] **Step 4: Run final verification**

Run:

```bash
.venv/bin/python -m pytest -q
.venv/bin/ruff check src tests scripts
.venv/bin/opportunity-radar run --sources state_council_policy_library
```

Expected: tests and Ruff exit 0. The CLI command exits non-zero with `not eligible: state_council_policy_library (phase=candidate)` before any HTTP request or LLM credential lookup.

- [ ] **Step 5: Commit documentation and final invariant test**

```bash
git add README.md docs/operations/policy-source-smoke-check.md tests/test_config.py
git commit -m "docs: describe compliant policy source activation"
```

## Plan Self-Review

- Spec coverage: Tasks 1–3 cover candidate defaults, documented terms/registration/rate/authorization/fields, fail-closed source selection, evidence and review data, no-secret storage, operator procedure and no-network rejection.
- Placeholder scan: no implementation placeholders; all JSON fields, interfaces, tests and commands are specified.
- Type consistency: `ComplianceSource`, `load_compliance_sources` and `blocking_reason` use the same names and return types in all tasks. CLI accepts `SourceConfig` from the existing config module and only passes selected IDs to existing adapters.
