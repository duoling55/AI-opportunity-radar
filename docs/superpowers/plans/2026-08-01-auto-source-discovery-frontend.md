# 自动信源发现 - 06 页面与信源集成 实现计划（Plan B）

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 在 Plan A 后端之上，新增 `06 信源搜索` 左侧导航页，承载发现模块全部前端功能（发起搜索、候选列表、核查报告与评分要素展示、人工审核、提升为正式信源）；与 `01 信源编辑` 交互；落地采集门控与新信源通用适配器。

**架构：** `compliance_sources.json` 为 discovery 信源唯一真源，`sources.json` 为运行时投影（promote 双写）。`GenericGovSource` 通用适配器按配置实例化。FR-02 采集选择过滤 `phase=verified AND enabled=true`。前端为原生 HTML/CSS/JS（无框架），复用现有 `setPage()` 机制。

**技术栈：** Python ≥3.11、http.server（手工路由）、原生 HTML/CSS/JS、pytest（API/服务层）、Playwright（可选 UI 冒烟）。

**前置依赖：** Plan A（`2026-08-01-auto-source-discovery-backend.md`）已完成，候选信源已可写入 `compliance_sources.json`。

**关联 spec：** `docs/superpowers/specs/2026-08-01-discovery-page-and-source-integration-design.md`

---

## 文件结构

**创建：**
- `src/opportunity_radar/sources/generic.py` - `GenericGovSource` 通用政府信源适配器
- `src/opportunity_radar/discovery/service.py` - promote / review / list_candidates 服务层
- `tests/sources/test_generic.py`
- `tests/test_discovery_service.py`
- `tests/test_discovery_api.py`

**修改：**
- `src/opportunity_radar/sources/registry.py` - 按 `adapter_version="generic"`/`origin="discovery"` 路由到 `GenericGovSource`
- `src/opportunity_radar/ui_server.py` - 新增发现 API 路由；放宽 `_validate_sources`（第 166-167 行）；采集信源选择门控
- `src/opportunity_radar/collection.py` - 采集前校验信源 `phase=verified AND enabled=true`
- `src/opportunity_radar/ui_static/index.html` - 新增 06 nav 按钮（第 27-43 行）与 `#page-search` section
- `src/opportunity_radar/ui_static/app.js` - 新增 `pages.search`（第 29-35 行）与渲染/轮询/审核逻辑
- `src/opportunity_radar/ui_static/styles.css` - origin/phase 徽标、核查结果/优先级颜色徽标

---

## 阶段 B：06 页面与信源集成

### 任务 B1：GenericGovSource 通用适配器

**文件：**
- 创建：`src/opportunity_radar/sources/generic.py`
- 修改：`src/opportunity_radar/sources/registry.py`
- 测试：`tests/sources/test_generic.py`

- [ ] **步骤 1：编写失败的测试**

```python
# tests/sources/test_generic.py
from opportunity_radar.sources.generic import GenericGovSource
from opportunity_radar.config import SourceConfig


def _config():
    return SourceConfig(source_id="gov_disc", display_name="发现信源", region="国家",
                        list_urls=("https://www.gov.cn/zc/index.html",),
                        allowed_domains=("www.gov.cn",), origin="discovery", adapter_version="generic")


def test_generic_source_discovers_from_html():
    html = '<a href="/p/1">关于设备更新的通知</a>'
    src = GenericGovSource(_config())
    cands = src.discover_from_html("https://www.gov.cn/zc/index.html", html, None, None)
    assert any("设备更新" in c.title for c in cands)


def test_registry_routes_generic_adapter():
    from opportunity_radar.sources.registry import resolve_adapter
    assert resolve_adapter(_config()) is GenericGovSource
```

> `discover_from_html` 签名与日期参数对齐 `GenericHtmlSource`（`sources/base.py` 第 71 行）；若基类签名含 `start`/`end` 日期，按基类填 `None` 或 `date`。

- [ ] **步骤 2：运行测试验证失败**

运行：`pytest tests/sources/test_generic.py -v`
预期：FAIL - `generic` 模块与 `resolve_adapter` 未定义。

- [ ] **步骤 3：编写实现**

```python
# src/opportunity_radar/sources/generic.py
from __future__ import annotations
from opportunity_radar.sources.base import GenericHtmlSource

# 政府门户政策列表常见选择器，可被 SourceConfig 覆盖
_DEFAULT_LISTING = "ul.list li a, .policy-list a, .list-content a, a"
_DEFAULT_DETAIL = ".content, .article, #zoom, .TRS_Editor"


class GenericGovSource(GenericHtmlSource):
    """按 sources.json 配置实例化的通用政府信源适配器，无需专用适配器文件。"""

    listing_item_selectors = (_DEFAULT_LISTING,)
    detail_content_selectors = (_DEFAULT_DETAIL,)

    def __init__(self, config) -> None:
        # 复用基类构造；适配 SourceConfig 字段
        super().__init__(
            source_id=config.source_id,
            list_urls=tuple(config.list_urls),
            allowed_domains=tuple(config.allowed_domains),
            request_interval=config.request_interval_seconds,
        )
        self.config = config
```

在 `sources/registry.py` 新增/修改解析函数（保留现有 source_id -> 专用适配器映射，新增 generic 路由）：

```python
# sources/registry.py
from opportunity_radar.sources.generic import GenericGovSource

def resolve_adapter(config):
    """专用适配器优先；origin=discovery 或 adapter_version=generic 走 GenericGovSource。"""
    dedicated = _DEDICATED_MAP.get(config.source_id)   # 现有 6 个适配器映射
    if dedicated is not None:
        return dedicated
    if getattr(config, "origin", None) == "discovery" or config.adapter_version == "generic":
        return GenericGovSource
    raise KeyError(f"无适配器: {config.source_id}")
```

> `_DEDICATED_MAP` 为现有 `source_id -> 适配器类` 映射；若 registry 现用不同结构（函数注册表或 if/elif），按其现有风格接入 `resolve_adapter`，保持现有 6 信源路由不变。

- [ ] **步骤 4：运行测试验证通过**

运行：`pytest tests/sources/test_generic.py -v`
预期：PASS

- [ ] **步骤 5：Lint + Commit**

```bash
ruff check src/opportunity_radar/sources/generic.py src/opportunity_radar/sources/registry.py tests/sources/test_generic.py
git add src/opportunity_radar/sources/generic.py src/opportunity_radar/sources/registry.py tests/sources/test_generic.py
git commit -m "feat(sources): GenericGovSource 通用适配器与 registry 路由"
```

---

### 任务 B2：发现服务层（promote / review / list_candidates）

**文件：**
- 创建：`src/opportunity_radar/discovery/service.py`
- 测试：`tests/test_discovery_service.py`

- [ ] **步骤 1：编写失败的测试**

```python
# tests/test_discovery_service.py
import json
from datetime import date
from opportunity_radar.discovery.service import DiscoveryService


def _candidate_file(tmp_path, phase="candidate", check_result="pass"):
    meta = {"keywords": ["设备更新"], "discovered_at": str(date(2026, 8, 1)), "portal_seed_id": "gov",
            "admin_level": "国家", "sample_policies": [], "snapshots": [],
            "check_result": check_result, "check_details": {}, "recommendation": "建议启用",
            "priority_score": 85, "priority_level": "高", "score_breakdown": []}
    rec = {"source_id": "gov_disc", "display_name": "国务院", "region": "国家", "phase": phase,
           "enabled": False, "official_urls": ["https://www.gov.cn/zc/"], "origin": "discovery", "discovery": meta}
    comp = tmp_path / "compliance_sources.json"; comp.write_text(json.dumps([rec]))
    srcs = tmp_path / "sources.json"; srcs.write_text("[]")
    return comp, srcs


def test_list_candidates_returns_only_discovery(tmp_path):
    comp, srcs = _candidate_file(tmp_path)
    svc = DiscoveryService(compliance_path=str(comp), sources_path=str(srcs))
    cands = svc.list_candidates()
    assert len(cands) == 1 and cands[0]["source_id"] == "gov_disc"


def test_promote_moves_to_verified_and_syncs_sources(tmp_path):
    comp, srcs = _candidate_file(tmp_path)
    svc = DiscoveryService(compliance_path=str(comp), sources_path=str(srcs))
    svc.promote("gov_disc", reviewer="admin")
    comp_data = json.loads(comp.read_text())
    assert comp_data[0]["phase"] == "verified" and comp_data[0]["enabled"] is True
    srcs_data = json.loads(srcs.read_text())
    assert srcs_data[0]["source_id"] == "gov_disc"
    assert srcs_data[0]["origin"] == "discovery" and srcs_data[0]["adapter_version"] == "generic"


def test_promote_not_recommended_requires_override(tmp_path):
    comp, srcs = _candidate_file(tmp_path, check_result="not_recommended")
    svc = DiscoveryService(compliance_path=str(comp), sources_path=str(srcs))
    import pytest
    with pytest.raises(ValueError, match="not_recommended"):
        svc.promote("gov_disc", reviewer="admin")
    svc.promote("gov_disc", reviewer="admin", override_not_recommended=True)
    assert json.loads(comp.read_text())[0]["phase"] == "verified"


def test_reject_retires_source(tmp_path):
    comp, srcs = _candidate_file(tmp_path)
    svc = DiscoveryService(compliance_path=str(comp), sources_path=str(srcs))
    svc.review("gov_disc", action="reject", reason="证据不足", reviewer="admin")
    rec = json.loads(comp.read_text())[0]
    assert rec["phase"] == "retired" and rec["enabled"] is False
```

- [ ] **步骤 2：运行测试验证失败**

运行：`pytest tests/test_discovery_service.py -v`
预期：FAIL - `service` 模块未定义。

- [ ] **步骤 3：编写实现**

```python
# src/opportunity_radar/discovery/service.py
from __future__ import annotations
import json
from datetime import date, datetime
from pathlib import Path


class DiscoveryService:
    def __init__(self, compliance_path: str = "config/compliance_sources.json",
                 sources_path: str = "config/sources.json") -> None:
        self._comp = Path(compliance_path)
        self._src = Path(sources_path)

    def list_candidates(self) -> list[dict]:
        return [r for r in self._read(self._comp) if r.get("origin") == "discovery"]

    def get_candidate(self, source_id: str) -> dict | None:
        for r in self._read(self._comp):
            if r["source_id"] == source_id and r.get("origin") == "discovery":
                return r
        return None

    def promote(self, source_id: str, reviewer: str, override_not_recommended: bool = False) -> dict:
        recs = self._read(self._comp)
        rec = self._find(recs, source_id)
        if rec.get("origin") != "discovery" or rec.get("phase") != "candidate":
            raise ValueError(f"无法提升：{source_id} 非候选信源")
        check = rec.get("discovery", {}).get("check_result")
        if check == "not_recommended" and not override_not_recommended:
            raise ValueError(f"not_recommended 信源需 override_not_recommended=True 二次确认")
        rec["phase"] = "verified"
        rec["enabled"] = True
        rec["verified_at"] = str(date.today())
        rec["owner"] = reviewer
        if override_not_recommended and check == "not_recommended":
            rec.setdefault("verification_notes", "override not_recommended")
        self._write(self._comp, recs)
        self._sync_sources(rec)
        return rec

    def review(self, source_id: str, action: str, reason: str | None, reviewer: str, comment: str = "") -> dict:
        recs = self._read(self._comp)
        rec = self._find(recs, source_id)
        if action == "confirm":
            return self.promote(source_id, reviewer=reviewer)
        if action == "reject":
            if not reason:
                raise ValueError("驳回必填原因")
            rec["phase"] = "retired"
            rec["enabled"] = False
            rec.setdefault("verification_notes", "")
            rec["verification_notes"] = f"驳回:{reason}; {comment}"
        elif action == "watch":
            rec.setdefault("verification_notes", "")
            rec["verification_notes"] += f"关注:{comment};"
        else:
            raise ValueError(f"未知动作: {action}")
        rec["reviewer"] = reviewer
        rec["reviewed_at"] = datetime.now().isoformat()
        self._write(self._comp, recs)
        return rec

    def _sync_sources(self, rec: dict) -> None:
        srcs = self._read(self._src)
        srcs = [s for s in srcs if s["source_id"] != rec["source_id"]]
        srcs.append({
            "source_id": rec["source_id"], "display_name": rec["display_name"], "region": rec["region"],
            "list_urls": rec.get("official_urls", []), "allowed_domains": self._domains(rec),
            "request_interval_seconds": 1.5, "adapter_version": "generic", "origin": "discovery",
            "enabled": True,
        })
        self._write(self._src, srcs)

    @staticmethod
    def _domains(rec: dict) -> list[str]:
        from urllib.parse import urlparse
        out = []
        for u in rec.get("official_urls", []):
            h = urlparse(u).hostname
            if h:
                out.append(h)
        return out

    @staticmethod
    def _find(recs, source_id):
        for r in recs:
            if r["source_id"] == source_id:
                return r
        raise ValueError(f"未找到信源: {source_id}")

    @staticmethod
    def _read(p: Path) -> list:
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() and p.read_text(encoding="utf-8").strip() else []

    @staticmethod
    def _write(p: Path, data) -> None:
        p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
```

- [ ] **步骤 4：运行测试验证通过**

运行：`pytest tests/test_discovery_service.py -v`
预期：PASS（4 项）。

- [ ] **步骤 5：Lint + Commit**

```bash
ruff check src/opportunity_radar/discovery/service.py tests/test_discovery_service.py
git add src/opportunity_radar/discovery/service.py tests/test_discovery_service.py
git commit -m "feat(discovery): promote/review/list_candidates 服务层"
```

---

### 任务 B3：发现 API 路由（ui_server.py）

**文件：**
- 修改：`src/opportunity_radar/ui_server.py`（`do_GET`/`do_POST`，第 642-713 行）
- 测试：`tests/test_discovery_api.py`

- [ ] **步骤 1：编写失败的测试**

```python
# tests/test_discovery_api.py
import json
from unittest.mock import patch
from opportunity_radar.ui_server import RadarRequestHandler


def _handler():
    h = RadarRequestHandler.__new__(RadarRequestHandler)  # 跳过 __init__ 的 socket 依赖
    return h


def test_get_candidates_returns_discovery(tmp_path):
    comp = tmp_path / "compliance_sources.json"
    comp.write_text(json.dumps([{"source_id": "g", "origin": "discovery", "phase": "candidate"}]))
    with patch("opportunity_radar.ui_server.DiscoveryService") as DS:
        DS.return_value.list_candidates.return_value = [{"source_id": "g", "origin": "discovery"}]
        h = _handler()
        body = h.handle_discovery_get_candidates()
    assert json.loads(body) == [{"source_id": "g", "origin": "discovery"}]


def test_promote_route_calls_service(tmp_path):
    with patch("opportunity_radar.ui_server.DiscoveryService") as DS:
        DS.return_value.promote.return_value = {"source_id": "g", "phase": "verified"}
        h = _handler()
        result = h.handle_discovery_promote("g", {"reviewer": "admin"})
    DS.return_value.promote.assert_called_once_with("g", reviewer="admin")
    assert result["phase"] == "verified"
```

> `handle_discovery_*` 为从 `do_GET`/`do_POST` 抽出的纯函数式 handler，便于单测不依赖 socket。若 `RadarRequestHandler.__init__` 强依赖 socket，用 `__new__` 绕过（见上）。

- [ ] **步骤 2：运行测试验证失败**

运行：`pytest tests/test_discovery_api.py -v`
预期：FAIL - `handle_discovery_*` 方法未定义。

- [ ] **步骤 3：编写实现**

在 `ui_server.py` 新增路由分发（`do_GET`/`do_POST` 第 642-713 行的 if/elif 链中加分支）：

```python
# do_GET 内
elif path == "/api/discovery/candidates":
    self._json(self.handle_discovery_get_candidates())
elif path.startswith("/api/discovery/reports/"):
    job_id = path.rsplit("/", 1)[-1]
    self._json(self.handle_discovery_report(job_id))
elif path.startswith("/api/discovery/candidates/"):
    source_id = path.rsplit("/", 1)[-1]
    self._json(self.handle_discovery_get_candidate(source_id))

# do_POST 内
elif path == "/api/discovery/search":
    self._json(self.handle_discovery_search(self._read_json_body()))
elif path.startswith("/api/discovery/candidates/") and path.endswith("/review"):
    source_id = path.split("/")[4]
    self._json(self.handle_discovery_review(source_id, self._read_json_body()))
elif path.startswith("/api/discovery/candidates/") and path.endswith("/promote"):
    source_id = path.split("/")[4]
    self._json(self.handle_discovery_promote(source_id, self._read_json_body()))
```

新增 handler 方法：

```python
from opportunity_radar.discovery.service import DiscoveryService

def _discovery_service(self):
    return DiscoveryService()

def handle_discovery_get_candidates(self):
    return self._discovery_service().list_candidates()

def handle_discovery_get_candidate(self, source_id):
    return self._discovery_service().get_candidate(source_id) or {}

def handle_discovery_review(self, source_id, body):
    return self._discovery_service().review(
        source_id, action=body["action"], reason=body.get("reason"),
        reviewer=body.get("reviewer", ""), comment=body.get("comment", ""))

def handle_discovery_promote(self, source_id, body):
    return self._discovery_service().promote(
        source_id, reviewer=body.get("reviewer", ""),
        override_not_recommended=body.get("override_not_recommended", False))

def handle_discovery_search(self, body):
    # 发起搜索任务：复用 _start_job() 启动 search-sources 子进程
    args = ["search-sources", "--keywords", body.get("keywords", "all"),
            "--portals", body.get("portals", "all")]
    job = self._start_job("信源搜索", args)   # 对齐现有 _start_job(label, arguments) 签名
    return {"job_id": job.job_id, "label": job.label}

def handle_discovery_report(self, job_id):
    from pathlib import Path
    p = Path(f"data/discovery/{job_id}-report.json")
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
```

> `_json`、`_read_json_body` 若不存在则新增：`_json` 写 `Content-Type: application/json` + body；`_read_json_body` 读 `Content-Length` 字节并 `json.loads`。`_start_job` 签名对齐第 358-394 行现有实现。

- [ ] **步骤 4：运行测试验证通过**

运行：`pytest tests/test_discovery_api.py -v`
预期：PASS

- [ ] **步骤 5：Lint + Commit**

```bash
ruff check src/opportunity_radar/ui_server.py tests/test_discovery_api.py
git add src/opportunity_radar/ui_server.py tests/test_discovery_api.py
git commit -m "feat(discovery): 发现 API 路由（search/candidates/review/promote/report）"
```

---

### 任务 B4：01 信源编辑约束放宽 + 采集门控

**文件：**
- 修改：`src/opportunity_radar/ui_server.py`（`_validate_sources` 第 166-167 行）
- 修改：`src/opportunity_radar/collection.py`（采集前信源选择校验）
- 测试：`tests/test_source_validation.py`

- [ ] **步骤 1：编写失败的测试**

```python
# tests/test_source_validation.py
import json
from opportunity_radar.ui_server import RadarRequestHandler


def test_validate_allows_new_discovery_source(tmp_path, monkeypatch):
    orig = [{"source_id": "miit", "display_name": "工信部", "region": "全国",
             "list_urls": ["https://www.miit.gov.cn"], "allowed_domains": ["www.miit.gov.cn"],
             "request_interval_seconds": 1.5, "adapter_version": "1.0.2", "origin": "manual"}]
    new_payload = orig + [{"source_id": "gov_disc", "display_name": "发现", "region": "国家",
             "list_urls": ["https://www.gov.cn/zc/"], "allowed_domains": ["www.gov.cn"],
             "request_interval_seconds": 1.5, "adapter_version": "generic", "origin": "discovery"}]
    h = RadarRequestHandler.__new__(RadarRequestHandler)
    # 应通过：新增的是 origin=discovery 且 adapter_version=generic
    assert h._validate_sources(new_payload, orig) is True


def test_validate_rejects_new_manual_source_without_adapter(tmp_path):
    orig = [{"source_id": "miit", "display_name": "工信部", "region": "全国",
             "list_urls": ["https://www.miit.gov.cn"], "allowed_domains": ["www.miit.gov.cn"],
             "request_interval_seconds": 1.5, "adapter_version": "1.0.2", "origin": "manual"}]
    new_payload = orig + [{"source_id": "random", "display_name": "随机", "region": "全国",
             "list_urls": ["https://random.com"], "allowed_domains": ["random.com"],
             "request_interval_seconds": 1.5, "adapter_version": "unregistered", "origin": "manual"}]
    h = RadarRequestHandler.__new__(RadarRequestHandler)
    import pytest
    with pytest.raises(ValueError):
        h._validate_sources(new_payload, orig)


def test_collectable_filter_excludes_candidate(tmp_path):
    from opportunity_radar.collection import filter_collectable
    sources = [
        {"source_id": "verified_gov", "origin": "discovery", "adapter_version": "generic"},
        {"source_id": "cand_gov", "origin": "discovery", "adapter_version": "generic"},
    ]
    comp = [
        {"source_id": "verified_gov", "phase": "verified", "enabled": True},
        {"source_id": "cand_gov", "phase": "candidate", "enabled": False},
    ]
    comp_path = tmp_path / "compliance_sources.json"
    comp_path.write_text(json.dumps(comp))
    selectable = filter_collectable(sources, compliance_path=str(comp_path))
    ids = [s["source_id"] for s in selectable]
    assert "verified_gov" in ids and "cand_gov" not in ids
```

- [ ] **步骤 2：运行测试验证失败**

运行：`pytest tests/test_source_validation.py -v`
预期：FAIL - `_validate_sources` 当前强制 `seen == original_ids`（第 166-167 行）；`filter_collectable` 未定义。

- [ ] **步骤 3：编写实现**

修改 `ui_server.py` `_validate_sources`（第 166-167 行），将"禁止任何新增"改为"仅允许 discovery+generic 新增"：

```python
def _validate_sources(self, payload, original):
    seen = {s["source_id"] for s in payload}
    original_ids = {s["source_id"] for s in original}
    # 禁止删除现有信源
    if not original_ids.issubset(seen):
        raise ValueError("不允许删除现有信源")
    # 禁止修改 source_id
    # 允许新增的信源：origin=discovery 且 adapter_version=generic
    new_ids = seen - original_ids
    for s in payload:
        if s["source_id"] in new_ids:
            if not (s.get("origin") == "discovery" and s.get("adapter_version") == "generic"):
                raise ValueError(f"新增信源 {s['source_id']} 必须为 origin=discovery 且 generic 适配器")
    return True
```

在 `collection.py` 新增 `filter_collectable`，采集前按合规台账过滤：

```python
# collection.py
import json
from pathlib import Path


def filter_collectable(sources: list[dict], compliance_path: str = "config/compliance_sources.json") -> list[dict]:
    """FR-02 采集门控：仅 phase=verified AND enabled=true 的信源可选。"""
    comp = {r["source_id"]: r for r in
            json.loads(Path(compliance_path).read_text(encoding="utf-8"))} if Path(compliance_path).exists() else {}
    out = []
    for s in sources:
        rec = comp.get(s["source_id"])
        if rec is not None:
            # discovery 信源须 verified+enabled
            if rec.get("origin") == "discovery" and not (rec.get("phase") == "verified" and rec.get("enabled")):
                continue
        out.append(s)
    return out
```

> 在 `collect_batch`（`collection.py`）选源处调用 `filter_collectable` 过滤后再采集；手动信源（manual，不在 compliance 台账或 phase=verified）保持现有行为。

- [ ] **步骤 4：运行测试验证通过**

运行：`pytest tests/test_source_validation.py -v`
预期：PASS（3 项）。

- [ ] **步骤 5：Lint + Commit**

```bash
ruff check src/opportunity_radar/ui_server.py src/opportunity_radar/collection.py tests/test_source_validation.py
git add src/opportunity_radar/ui_server.py src/opportunity_radar/collection.py tests/test_source_validation.py
git commit -m "feat(sources): 放宽 01 新增 discovery 信源约束 + 采集门控"
```

---

### 任务 B5：06 信源搜索前端页面

**文件：**
- 修改：`src/opportunity_radar/ui_static/index.html`（nav 第 27-43 行 + 新 section）
- 修改：`src/opportunity_radar/ui_static/app.js`（pages 第 29-35 行 + setPage 第 172-183 行 + 渲染逻辑）
- 修改：`src/opportunity_radar/ui_static/styles.css`

> 前端为原生 JS，无 JS 测试框架；以 API 层测试（B3）+ 手动冒烟（B6）保证质量。HTML/CSS/JS 变更遵循现有 `#page-sources` 与 `setPage()` 模式。

- [ ] **步骤 1：index.html 新增 06 导航与页面区块**

在 `<nav id="navigation">`（第 27-43 行）末尾、`</nav>` 前加：

```html
  <button class="nav-item" data-page="search"><b>06</b><span>信源搜索</span></button>
```

在 `#page-results` section 之后加：

```html
<section id="page-search" class="page">
  <header class="page-header">
    <h1 id="search-title">信源搜索</h1>
    <p id="search-subtitle" class="muted">基于知识库关键词自动发现政府政策信源，核查评分后确认启用。</p>
  </header>

  <div class="card search-launch">
    <div class="row">
      <label>关键词标签 <select id="search-keywords"><option value="all">全部</option></select></label>
      <label>门户种子 <select id="search-portals"><option value="all">全部</option></select></label>
      <button id="search-start-btn" class="btn primary">发起搜索</button>
    </div>
    <div id="search-progress" class="progress hidden"></div>
  </div>

  <div class="card">
    <h2>候选信源</h2>
    <div id="search-candidates" class="candidate-list"></div>
  </div>

  <div id="search-detail-drawer" class="drawer hidden">
    <div class="drawer-content">
      <button class="drawer-close" onclick="closeSearchDrawer()">✕</button>
      <div id="search-detail-body"></div>
    </div>
  </div>
</section>
```

- [ ] **步骤 2：app.js 注册页面 + 渲染逻辑**

在 `pages` 字典（第 29-35 行）加：

```javascript
  search: ["信源搜索", "基于知识库关键词自动发现政府政策信源，核查评分后确认启用。"],
```

在 `setPage()`（第 172-183 行）加 `search` 分支，进入时拉取候选：

```javascript
async function loadSearchCandidates() {
  const res = await fetch('/api/discovery/candidates');
  const data = await res.json();
  const box = document.getElementById('search-candidates');
  box.innerHTML = (data || []).map(c => candidateCard(c)).join('') || '<p class="muted">暂无候选信源</p>';
}

function candidateCard(c) {
  const d = c.discovery || {};
  const checkBadge = checkBadgeHtml(d.check_result);
  const prioBadge = priorityBadgeHtml(d.priority_level);
  return `<div class="candidate-card">
    <div class="candidate-head">
      <strong>${c.display_name}</strong> ${checkBadge} ${prioBadge}
      <span class="muted">${c.region} · ${d.admin_level || ''}</span>
    </div>
    <div class="candidate-meta muted">${(c.official_urls||[]).join(' · ')}</div>
    <div class="candidate-score">评分 <b>${d.priority_score ?? '-'}</b> · 样例 ${d.sample_policies?.length || 0} · 命中 ${(d.keywords||[]).join('、')}</div>
    <div class="candidate-actions">
      <button class="btn" onclick="openSearchDetail('${c.source_id}')">展开详情</button>
      <button class="btn primary" onclick="promoteCandidate('${c.source_id}')">确认启用</button>
      <button class="btn" onclick="reviewCandidate('${c.source_id}','watch')">标记关注</button>
    </div>
  </div>`;
}

function checkBadgeHtml(r) {
  const m = {pass:['pass','建议启用'], needs_attention:['warn','需关注'], not_recommended:['bad','不建议']};
  const [cls, txt] = m[r] || ['',''];
  return cls ? `<span class="badge ${cls}">${txt}</span>` : '';
}
function priorityBadgeHtml(l) {
  const m = {'高':'high','中':'mid','低':'low'};
  return l ? `<span class="badge ${m[l]||''}">${l}</span>` : '';
}

async function openSearchDetail(id) {
  const res = await fetch(`/api/discovery/candidates/${id}`);
  const c = await res.json();
  const d = c.discovery || {};
  const breakdown = (d.score_breakdown||[]).map(b => `<li>${b.dimension}: <b>${b.score}</b>/${b.max} <span class="muted">${b.reason}</span></li>`).join('');
  const samples = (d.sample_policies||[]).map(p => `<li><a href="${p.url}" target="_blank">${p.title}</a> <span class="muted">命中 ${p.matched_keywords?.join('、')}</span></li>`).join('');
  document.getElementById('search-detail-body').innerHTML = `
    <h2>${c.display_name}</h2>
    <section><h3>核查报告</h3><pre>${JSON.stringify(d.check_details||{}, null, 2)}</pre>
      <p>结论: ${d.check_result} · 建议: ${d.recommendation}</p></section>
    <section><h3>评分要素</h3><ul>${breakdown}</ul><p>总分 <b>${d.priority_score}</b> · ${d.priority_level}</p></section>
    <section><h3>样例政策</h3><ul>${samples}</ul></section>
    <section><h3>HTML 快照</h3><div>${(d.snapshots||[]).map(s=>`<a href="/static/${s}" target="_blank">${s}</a>`).join(' ')||'无'}</div></section>
    <div class="candidate-actions">
      <button class="btn primary" onclick="promoteCandidate('${id}')">确认启用</button>
      <button class="btn" onclick="reviewCandidate('${id}','reject')">驳回</button>
      <button class="btn" onclick="reviewCandidate('${id}','watch')">标记关注</button>
    </div>`;
  document.getElementById('search-detail-drawer').classList.remove('hidden');
}
function closeSearchDrawer() { document.getElementById('search-detail-drawer').classList.add('hidden'); }

async function promoteCandidate(id) {
  const c = (await (await fetch(`/api/discovery/candidates/${id}`)).json()).discovery||{};
  let override = false;
  if (c.check_result === 'not_recommended' && !confirm('该信源为 not_recommended，确认强制提升？')) return;
  if (c.check_result === 'not_recommended') override = true;
  await fetch(`/api/discovery/candidates/${id}/promote`, {method:'POST',
    headers:{'Content-Type':'application/json'},
    body: JSON.stringify({reviewer:'admin', override_not_recommended: override})});
  loadSearchCandidates();
}
async function reviewCandidate(id, action) {
  const reason = action==='reject' ? prompt('驳回原因') : '';
  await fetch(`/api/discovery/candidates/${id}/review`, {method:'POST',
    headers:{'Content-Type':'application/json'},
    body: JSON.stringify({action, reason: reason||null, reviewer:'admin'})});
  loadSearchCandidates();
}

document.getElementById('search-start-btn')?.addEventListener('click', async () => {
  const keywords = document.getElementById('search-keywords').value;
  const portals = document.getElementById('search-portals').value;
  const prog = document.getElementById('search-progress');
  prog.classList.remove('hidden');
  prog.textContent = '搜索任务已发起…';
  await fetch('/api/discovery/search', {method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({keywords, portals})});
  // 复用现有 jobs 轮询；任务完成后刷新候选
  setTimeout(loadSearchCandidates, 4000);
});
```

在 `setPage` 的 `search` 分支调用 `loadSearchCandidates()`。

- [ ] **步骤 3：styles.css 新增徽标与卡片样式**

```css
.badge { display:inline-block; padding:2px 8px; border-radius:10px; font-size:12px; margin:0 2px; }
.badge.pass, .badge.high { background:#e6f4ea; color:#1e7e34; }
.badge.warn, .badge.mid { background:#fff8e1; color:#8a6d3b; }
.badge.bad, .badge.low { background:#fdecea; color:#a1261d; }
.candidate-card { border:1px solid #e0e0e0; border-radius:8px; padding:12px; margin:8px 0; }
.candidate-head { display:flex; align-items:center; gap:8px; }
.candidate-actions { margin-top:8px; display:flex; gap:8px; }
.drawer { position:fixed; top:0; right:0; width:50%; height:100%; background:#fff;
  box-shadow:-2px 0 8px rgba(0,0,0,.15); overflow:auto; z-index:100; }
.drawer-content { padding:16px; }
.hidden { display:none; }
```

- [ ] **步骤 4：手动冒烟验证**

启动 UI（按项目现有方式），进入 06 信源搜索：
- 候选列表渲染（若无候选显示"暂无候选信源"）
- 发起搜索 -> 进度提示 -> 候选刷新
- 展开详情 -> 核查报告/评分要素/样例政策/快照
- 确认启用 -> 该信源从候选移除/标记，01 信源编辑可见

- [ ] **步骤 5：Commit**

```bash
git add src/opportunity_radar/ui_static/index.html src/opportunity_radar/ui_static/app.js src/opportunity_radar/ui_static/styles.css
git commit -m "feat(ui): 06 信源搜索页面（候选列表/详情/审核/提升）"
```

---

### 任务 B6：UI 端到端集成验证

**文件：**
- 测试：`tests/test_discovery_e2e_integration.py`

- [ ] **步骤 1：编写集成测试（服务层 + 门控 + 01 联动）**

```python
# tests/test_discovery_e2e_integration.py
import json
from opportunity_radar.discovery.service import DiscoveryService
from opportunity_radar.collection import filter_collectable


def test_promoted_source_is_collectable_and_unverified_is_not(tmp_path):
    comp = tmp_path / "compliance_sources.json"
    srcs = tmp_path / "sources.json"
    comp.write_text(json.dumps([
        {"source_id": "gov_a", "display_name": "A", "region": "国家", "phase": "candidate",
         "enabled": False, "official_urls": ["https://www.gov.cn/zc/"], "origin": "discovery",
         "discovery": {"check_result": "pass", "priority_score": 85, "priority_level": "高",
                       "keywords": [], "discovered_at": "2026-08-01", "portal_seed_id": "g",
                       "admin_level": "国家", "sample_policies": [], "snapshots": [],
                       "check_details": {}, "recommendation": "建议启用", "score_breakdown": []}},
    ]))
    srcs.write_text("[]")

    svc = DiscoveryService(compliance_path=str(comp), sources_path=str(srcs))
    # 未 promote 前，候选不可采集
    selectable = filter_collectable([{"source_id": "gov_a", "origin": "discovery"}], compliance_path=str(comp))
    assert selectable == []

    # promote 后同步 sources.json 且可采集
    svc.promote("gov_a", reviewer="admin")
    srcs_data = json.loads(srcs.read_text())
    selectable = filter_collectable(srcs_data, compliance_path=str(comp))
    assert [s["source_id"] for s in selectable] == ["gov_a"]
```

- [ ] **步骤 2：运行集成测试**

运行：`pytest tests/test_discovery_e2e_integration.py -v`
预期：PASS

- [ ] **步骤 3：全量回归**

```bash
pytest tests/ -v
ruff check src/opportunity_radar/
```
预期：全绿。

- [ ] **步骤 4：Commit**

```bash
git add tests/test_discovery_e2e_integration.py
git commit -m "test(discovery): promote 后可采集、未核验不可采集的端到端验证"
```

---

## 自检

**1. 规格覆盖度（Spec 5）：**
- 06 导航页 + 候选列表 + 详情抽屉 + 审核/提升：B5 ✅
- 发现 API（search/candidates/review/promote/report）：B3 ✅
- promote 双写 compliance+sources、not_recommended 二次确认：B2 ✅
- 01 约束放宽（允许 discovery+generic 新增）：B4 ✅
- 通用适配器 GenericGovSource + registry 路由：B1 ✅
- 采集门控（verified AND enabled）：B4 ✅
- discovery 信源经通用适配器可采集：B1（GenericGovSource 复用 GenericHtmlSource.discover）✅
- 数据模型 origin（SourceConfig）：Plan A 任务 A0 ✅

**2. 占位符扫描：** 无 TODO/待定；`_start_job`/`_json`/`_read_json_body` 已注明对齐现有签名，若缺失则新增（已给出实现）。

**3. 类型一致性：** `DiscoveryService.promote/review/list_candidates` 签名在 B2 定义、B3 调用一致（`reviewer`/`override_not_recommended`/`action`/`reason`）。`filter_collectable` 在 B4 定义、B6 调用一致。前端 `promoteCandidate` 传 `override_not_recommended` 与 B2/B3 一致。

**4. 跨计划一致性：** Plan B 消费 Plan A 产出的 `compliance_sources.json` 候选（`origin=discovery`/`phase=candidate`/`discovery.*` 字段），字段名与 Plan A 任务 A0/A5 一致（`discovery.check_result`/`priority_score`/`score_breakdown`/`sample_policies`/`snapshots`）。

---

## 执行交接

Plan B 已完成并保存到 `docs/superpowers/plans/2026-08-01-auto-source-discovery-frontend.md`。

**两个计划已就绪：**
- Plan A（后端发现引擎）：`2026-08-01-auto-source-discovery-backend.md`
- Plan B（前端 06 页面与信源集成，依赖 Plan A）：`2026-08-01-auto-source-discovery-frontend.md`

两种执行方式：

**1. 子代理驱动（推荐）** - 每个任务调度一个新的子代理，任务间审查，快速迭代
**2. 内联执行** - 在当前会话中使用 executing-plans 执行任务，批量执行并设检查点

选哪种方式？建议先执行 Plan A，完成后审查再执行 Plan B。
