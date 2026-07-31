# Policy Opportunity Radar Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a manually runnable Python Skill that collects recent official policies from national, Zhejiang, and Jiangsu sources, uses AI to identify industry opportunities, and exports traceable Excel workbooks.

**Architecture:** Source-specific adapters discover and retrieve public policy pages; parsing, normalization, snapshots, and deduplication stay deterministic in Python. An OpenAI-compatible analysis adapter receives normalized policy text and returns schema-validated JSON; quality rules score and route each policy × industry record into either `重点商机` or `政策观察` before an Excel exporter writes the workbook and run report.

**Tech Stack:** Python 3.11+ (workspace currently has 3.13), `httpx`, `beautifulsoup4`, `pypdf`, `python-docx`, `openpyxl`, `pydantic`, `pytest`, and standard-library SQLite.

## Global Constraints

- Default query range is the prior 30 calendar days; `--start-date` and `--end-date` override it; first-run backfill may use 90 days.
- Only request enabled, allow-listed official domains; never bypass logins, CAPTCHAs, rate limits, or other access controls.
- Retain source URL, policy title, publisher, date, source snapshot, content hash, and collection timestamp for every output record.
- Treat one row as one `policy × industry opportunity`; write exactly two business sheets: `重点商机` and `政策观察`.
- `重点商机` requires complete source, industry, opportunity-scenario, and original-evidence fields; missing evidence always routes to `政策观察`.
- Use GB/T 4754—2017 plus Amendment No. 1 as the standard industry-code source; allow only codes from the imported local code table.
- Do not search for companies or collect personal data in this release.
- Block wording that promises policy eligibility, subsidy receipt, financing approval, or government endorsement.
- A failed source, attachment, or AI call must be logged and must not stop other sources from exporting results.
- Never overwrite an existing workbook; add a timestamp suffix when the target filename already exists.

---

## Planned File Structure

```text
pyproject.toml
README.md
config/
  sources.json                         # Official-source allowlists and list endpoints
  business_industries.json             # Readable business-industry labels
data/industry/
  gbt_4754_2017.json                   # Imported official code table, versioned
scripts/
  import_industry_classification.py    # Turns official CSV/XLSX export into the local JSON table
src/opportunity_radar/
  __init__.py
  cli.py                               # `opportunity-radar run` entry point
  config.py                            # Typed runtime and source configuration
  industry.py                          # Loads the versioned local industry-code table
  models.py                            # Pydantic domain contracts
  http.py                              # Polite allow-listed HTTP client
  state.py                             # SQLite state and deduplication
  sources/
    base.py                             # Candidate discovery and source protocol
    registry.py                         # Enabled source registry
    miit.py
    ndrc.py
    zhejiang_huiqi.py
    zhejiang_eit.py
    jiangsu_government.py
    jiangsu_eit.py
  parsing/
    html.py
    attachments.py
    snapshot.py
  analysis/
    prompts.py
    client.py
  quality/
    scoring.py
    validation.py
    scripts.py
  export/
    excel.py
    report.py
  pipeline.py
tests/
  conftest.py
  fixtures/
  test_config.py
  test_models.py
  test_state.py
  sources/
  parsing/
  analysis/
  quality/
  export/
  test_pipeline.py
```

## Task 1: Bootstrap the Python package and checked-in runtime configuration

**Files:**

- Create: `pyproject.toml`
- Create: `README.md`
- Create: `src/opportunity_radar/__init__.py`
- Create: `src/opportunity_radar/config.py`
- Create: `config/sources.json`
- Create: `config/business_industries.json`
- Create: `tests/test_config.py`

**Interfaces:**

- Produces `SourceConfig`, `RunConfig`, and `load_sources(path: Path) -> dict[str, SourceConfig]` for every later task.
- Produces the console command `opportunity-radar`, implemented in Task 9.

- [ ] **Step 1: Write the failing configuration test**

```python
# tests/test_config.py
from pathlib import Path

from opportunity_radar.config import RunConfig, load_sources


def test_load_sources_and_default_window() -> None:
    sources = load_sources(Path("config/sources.json"))
    assert {"miit", "ndrc", "zhejiang_huiqi", "zhejiang_eit", "jiangsu_government", "jiangsu_eit"} <= set(sources)
    assert sources["miit"].allowed_domains == ("www.miit.gov.cn",)
    config = RunConfig.from_optional_dates(None, None, source_ids=("miit",))
    assert config.start_date < config.end_date
    assert (config.end_date - config.start_date).days == 30
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/test_config.py -v`

Expected: FAIL because `opportunity_radar.config` does not exist.

- [ ] **Step 3: Add project metadata, package scaffolding, and typed config**

```toml
# pyproject.toml
[build-system]
requires = ["hatchling>=1.25"]
build-backend = "hatchling.build"

[project]
name = "opportunity-radar"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
  "beautifulsoup4>=4.12,<5",
  "httpx>=0.27,<1",
  "openpyxl>=3.1,<4",
  "pydantic>=2.8,<3",
  "pypdf>=4.3,<6",
  "python-docx>=1.1,<2",
]

[project.optional-dependencies]
dev = ["pytest>=8,<9", "pytest-httpx>=0.30,<1", "ruff>=0.6,<1"]

[project.scripts]
opportunity-radar = "opportunity_radar.cli:main"

[tool.pytest.ini_options]
pythonpath = ["src"]
testpaths = ["tests"]

[tool.ruff]
line-length = 100
target-version = "py311"
```

```python
# src/opportunity_radar/config.py
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path


@dataclass(frozen=True)
class SourceConfig:
    source_id: str
    display_name: str
    region: str
    list_urls: tuple[str, ...]
    allowed_domains: tuple[str, ...]
    enabled: bool = True
    request_interval_seconds: float = 1.0


@dataclass(frozen=True)
class RunConfig:
    start_date: date
    end_date: date
    source_ids: tuple[str, ...]
    output_dir: Path = Path("outputs")
    state_path: Path = Path("data/state/radar.sqlite3")
    raw_dir: Path = Path("data/raw")
    normalized_dir: Path = Path("data/normalized")

    @classmethod
    def from_optional_dates(
        cls, start_date: date | None, end_date: date | None, source_ids: tuple[str, ...]
    ) -> "RunConfig":
        resolved_end = end_date or date.today()
        resolved_start = start_date or resolved_end - timedelta(days=30)
        if resolved_start >= resolved_end:
            raise ValueError("start_date must be earlier than end_date")
        return cls(resolved_start, resolved_end, source_ids)


def load_sources(path: Path) -> dict[str, SourceConfig]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return {
        item["source_id"]: SourceConfig(
            source_id=item["source_id"],
            display_name=item["display_name"],
            region=item["region"],
            list_urls=tuple(item["list_urls"]),
            allowed_domains=tuple(item["allowed_domains"]),
            enabled=item.get("enabled", True),
            request_interval_seconds=float(item.get("request_interval_seconds", 1.0)),
        )
        for item in payload
    }
```

```json
// config/sources.json
[
  {"source_id":"miit","display_name":"工业和信息化部","region":"全国","list_urls":["https://www.miit.gov.cn/gyhxxhbwjcx/"],"allowed_domains":["www.miit.gov.cn"],"request_interval_seconds":1.5},
  {"source_id":"ndrc","display_name":"国家发展改革委","region":"全国","list_urls":["https://www.ndrc.gov.cn/xxgk/wjk/index.html"],"allowed_domains":["www.ndrc.gov.cn","zfxxgk.ndrc.gov.cn"],"request_interval_seconds":1.5},
  {"source_id":"zhejiang_huiqi","display_name":"浙江省惠企政策信息平台","region":"浙江","list_urls":["https://zj87.jxt.zj.gov.cn/zjhqpt/views/policy-zw/list.html"],"allowed_domains":["zj87.jxt.zj.gov.cn"],"request_interval_seconds":2.0},
  {"source_id":"zhejiang_eit","display_name":"浙江省经济和信息化厅","region":"浙江","list_urls":["https://jxt.zj.gov.cn/"],"allowed_domains":["jxt.zj.gov.cn"],"request_interval_seconds":1.5},
  {"source_id":"jiangsu_government","display_name":"江苏省人民政府","region":"江苏","list_urls":["https://www.jiangsu.gov.cn/col/col84242/index.html"],"allowed_domains":["www.jiangsu.gov.cn"],"request_interval_seconds":1.5},
  {"source_id":"jiangsu_eit","display_name":"江苏省工业和信息化厅","region":"江苏","list_urls":["https://gxt.jiangsu.gov.cn/"],"allowed_domains":["gxt.jiangsu.gov.cn"],"request_interval_seconds":1.5}
]
```

```json
// config/business_industries.json
[
  "新能源", "光伏与储能", "汽车及零部件", "通用装备制造", "专用设备制造",
  "纺织与服装", "化工与新材料", "医药与医疗器械", "食品加工", "物流与商用车",
  "数字化与软件", "节能环保"
]
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `pytest tests/test_config.py -v`

Expected: PASS.

- [ ] **Step 5: Commit the bootstrap**

```bash
git add pyproject.toml README.md config src/opportunity_radar/__init__.py src/opportunity_radar/config.py tests/test_config.py
git commit -m "feat: bootstrap policy radar package"
```

## Task 2: Define validated domain contracts and import the industry-code table

**Files:**

- Create: `src/opportunity_radar/models.py`
- Create: `src/opportunity_radar/industry.py`
- Create: `scripts/import_industry_classification.py`
- Create: `tests/test_models.py`
- Create: `tests/fixtures/industry_codes.csv`
- Create: `tests/test_industry_import.py`
- Create: `data/industry/gbt_4754_2017.json`

**Interfaces:**

- Produces `PolicyCandidate`, `PolicyDocument`, `Evidence`, `IndustryOpportunity`, and `PolicyAnalysis`.
- Produces `load_industry_codes(path: Path) -> set[str]` used by the analysis validator in Task 6.

- [ ] **Step 1: Write failing model and importer tests**

```python
# tests/test_models.py
from datetime import date

import pytest

from opportunity_radar.models import Evidence, IndustryOpportunity


def test_industry_opportunity_rejects_unknown_confidence() -> None:
    with pytest.raises(ValueError):
        IndustryOpportunity(
            section_code="C", section_name="制造业", division_code="C34",
            division_name="通用设备制造业", business_tags=["通用装备制造"],
            confidence=1.2, scenarios=["设备更新"], evidence=[Evidence(quote="设备更新", location="第2段")],
        )
```

```python
# tests/test_industry_import.py
from pathlib import Path

from scripts.import_industry_classification import import_codes


def test_import_codes_writes_deduplicated_json(tmp_path: Path) -> None:
    output = tmp_path / "codes.json"
    import_codes(Path("tests/fixtures/industry_codes.csv"), output)
    assert '"C34"' in output.read_text(encoding="utf-8")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_models.py tests/test_industry_import.py -v`

Expected: FAIL because the models and importer are absent.

- [ ] **Step 3: Implement the Pydantic contracts and importer**

```python
# src/opportunity_radar/models.py
from __future__ import annotations

from datetime import date, datetime
from pydantic import BaseModel, Field, HttpUrl, field_validator


class PolicyCandidate(BaseModel):
    source_id: str
    title: str
    detail_url: HttpUrl
    published_at: date | None = None


class PolicyDocument(BaseModel):
    policy_id: str
    source_id: str
    source_name: str
    region: str
    title: str
    detail_url: HttpUrl
    publisher: str | None = None
    document_number: str | None = None
    publish_date: date | None = None
    effective_date: date | None = None
    application_start_date: date | None = None
    application_end_date: date | None = None
    raw_text: str
    normalized_text: str
    attachment_urls: list[HttpUrl] = Field(default_factory=list)
    collected_at: datetime
    content_hash: str
    snapshot_path: str


class Evidence(BaseModel):
    quote: str = Field(min_length=2, max_length=240)
    location: str = Field(min_length=1, max_length=80)


class IndustryOpportunity(BaseModel):
    section_code: str
    section_name: str
    division_code: str
    division_name: str
    business_tags: list[str] = Field(min_length=1)
    confidence: float = Field(ge=0, le=1)
    scenarios: list[str] = Field(min_length=1)
    evidence: list[Evidence] = Field(min_length=1)
    leasing_relevance: str
    recommended_action: str
    opening_script: str


class PolicyAnalysis(BaseModel):
    is_benefit_policy: bool
    summary: str
    support_direction: str
    eligible_conditions: str | None = None
    risk_notes: str | None = None
    opportunities: list[IndustryOpportunity] = Field(default_factory=list)

    @field_validator("opportunities")
    @classmethod
    def non_benefit_policy_has_no_opportunities(cls, value: list[IndustryOpportunity], info):
        if info.data.get("is_benefit_policy") is False and value:
            raise ValueError("non-benefit policy cannot contain opportunities")
        return value
```

```python
# scripts/import_industry_classification.py
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path


def import_codes(source: Path, output: Path) -> None:
    with source.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    records = sorted(
        {row["code"].strip(): {"code": row["code"].strip(), "name": row["name"].strip()} for row in rows}.values(),
        key=lambda item: item["code"],
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    import_codes(Path(sys.argv[1]), Path(sys.argv[2]))
```

```python
# src/opportunity_radar/industry.py
import json
from pathlib import Path


def load_industry_codes(path: Path) -> set[str]:
    return {item["code"] for item in json.loads(path.read_text(encoding="utf-8"))}
```

```csv
# tests/fixtures/industry_codes.csv
code,name
C,制造业
C34,通用设备制造业
C36,汽车制造业
```

Use the official GB/T 4754—2017 (Amendment No. 1) source file to create `data/industry/gbt_4754_2017.json` with:

```bash
python scripts/import_industry_classification.py /absolute/path/to/official-industry-codes.csv data/industry/gbt_4754_2017.json
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_models.py tests/test_industry_import.py -v`

Expected: PASS.

- [ ] **Step 5: Commit contracts and industry data import path**

```bash
git add src/opportunity_radar/models.py src/opportunity_radar/industry.py scripts/import_industry_classification.py data/industry tests
git commit -m "feat: add policy domain contracts and industry importer"
```

## Task 3: Add snapshots, normalization, and SQLite-backed incremental deduplication

**Files:**

- Create: `src/opportunity_radar/parsing/snapshot.py`
- Create: `src/opportunity_radar/normalization.py`
- Create: `src/opportunity_radar/state.py`
- Create: `tests/test_state.py`

**Interfaces:**

- Consumes `PolicyCandidate` and raw text.
- Produces `make_policy_id(candidate: PolicyCandidate) -> str`, `content_hash(text: str) -> str`, and `StateStore.is_changed(policy_id: str, content_hash: str) -> bool`.

- [ ] **Step 1: Write the failing deduplication test**

```python
# tests/test_state.py
from pathlib import Path

from opportunity_radar.models import PolicyCandidate
from opportunity_radar.normalization import content_hash, make_policy_id
from opportunity_radar.state import StateStore


def test_state_store_skips_unchanged_and_accepts_updated_content(tmp_path: Path) -> None:
    candidate = PolicyCandidate(source_id="miit", title="设备更新通知", detail_url="https://www.miit.gov.cn/art/1.html")
    policy_id = make_policy_id(candidate)
    first_hash = content_hash("正文一")
    store = StateStore(tmp_path / "state.sqlite3")
    assert store.is_changed(policy_id, first_hash) is True
    store.record_success(policy_id, first_hash)
    assert store.is_changed(policy_id, first_hash) is False
    assert store.is_changed(policy_id, content_hash("正文二")) is True
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/test_state.py -v`

Expected: FAIL because normalization and state modules do not exist.

- [ ] **Step 3: Implement stable IDs, hashes, snapshots, and state**

```python
# src/opportunity_radar/normalization.py
from __future__ import annotations

import hashlib
import re
from urllib.parse import urlsplit, urlunsplit

from opportunity_radar.models import PolicyCandidate


def normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def canonical_url(value: str) -> str:
    parts = urlsplit(value)
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path.rstrip("/"), "", ""))


def make_policy_id(candidate: PolicyCandidate) -> str:
    seed = f"{candidate.source_id}|{canonical_url(str(candidate.detail_url))}"
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()[:24]


def content_hash(text: str) -> str:
    return hashlib.sha256(normalize_text(text).encode("utf-8")).hexdigest()
```

```python
# src/opportunity_radar/state.py
from __future__ import annotations

import sqlite3
from pathlib import Path


class StateStore:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(path)
        self.connection.execute("CREATE TABLE IF NOT EXISTS policies (policy_id TEXT PRIMARY KEY, content_hash TEXT NOT NULL)")

    def is_changed(self, policy_id: str, value: str) -> bool:
        row = self.connection.execute("SELECT content_hash FROM policies WHERE policy_id = ?", (policy_id,)).fetchone()
        return row is None or row[0] != value

    def record_success(self, policy_id: str, value: str) -> None:
        self.connection.execute(
            "INSERT INTO policies(policy_id, content_hash) VALUES (?, ?) ON CONFLICT(policy_id) DO UPDATE SET content_hash=excluded.content_hash",
            (policy_id, value),
        )
        self.connection.commit()
```

```python
# src/opportunity_radar/parsing/snapshot.py
from datetime import datetime, timezone
from pathlib import Path


def save_snapshot(root: Path, policy_id: str, suffix: str, body: bytes) -> Path:
    destination = root / datetime.now(timezone.utc).strftime("%Y%m%d") / f"{policy_id}.{suffix}"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(body)
    return destination
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `pytest tests/test_state.py -v`

Expected: PASS.

- [ ] **Step 5: Commit deterministic persistence**

```bash
git add src/opportunity_radar/normalization.py src/opportunity_radar/state.py src/opportunity_radar/parsing/snapshot.py tests/test_state.py
git commit -m "feat: add policy snapshots and incremental dedupe"
```

## Task 4: Implement polite official-source discovery and retrieval adapters

**Files:**

- Create: `src/opportunity_radar/http.py`
- Create: `src/opportunity_radar/sources/base.py`
- Create: `src/opportunity_radar/sources/registry.py`
- Create: `src/opportunity_radar/sources/miit.py`
- Create: `src/opportunity_radar/sources/ndrc.py`
- Create: `src/opportunity_radar/sources/zhejiang_huiqi.py`
- Create: `src/opportunity_radar/sources/zhejiang_eit.py`
- Create: `src/opportunity_radar/sources/jiangsu_government.py`
- Create: `src/opportunity_radar/sources/jiangsu_eit.py`
- Create: `tests/sources/test_base.py`
- Create: `tests/sources/test_registry.py`
- Create: `tests/fixtures/listing.html`

**Interfaces:**

- Produces `OfficialHttpClient.get(url: str) -> httpx.Response` and `PolicySource.discover(start: date, end: date) -> list[PolicyCandidate]`.
- The registry exposes `build_sources(configs: dict[str, SourceConfig]) -> dict[str, PolicySource]`; it creates one polite client per source.

- [ ] **Step 1: Write failing allowlist and discovery tests**

```python
# tests/sources/test_base.py
from datetime import date

import pytest

from opportunity_radar.config import SourceConfig
from opportunity_radar.http import OfficialHttpClient
from opportunity_radar.sources.base import GenericHtmlSource


def test_discovery_extracts_detail_link_and_date(httpx_mock) -> None:
    config = SourceConfig("demo", "演示", "全国", ("https://policy.example.gov.cn/list",), ("policy.example.gov.cn",))
    httpx_mock.add_response(url="https://policy.example.gov.cn/list", text='<a href="/art/1.html">设备更新通知</a><span>2026-07-20</span>')
    result = GenericHtmlSource(config, OfficialHttpClient(config)).discover(date(2026, 7, 1), date(2026, 7, 30))
    assert result[0].detail_url == "https://policy.example.gov.cn/art/1.html"


def test_client_rejects_non_official_domain() -> None:
    config = SourceConfig("demo", "演示", "全国", (), ("policy.example.gov.cn",))
    with pytest.raises(ValueError, match="allow-listed"):
        OfficialHttpClient(config).get("https://not-official.example/list")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/sources -v`

Expected: FAIL because source and HTTP modules are absent.

- [ ] **Step 3: Implement the allow-listed client and common adapter**

```python
# src/opportunity_radar/http.py
from __future__ import annotations

import time
from urllib.parse import urlparse

import httpx

from opportunity_radar.config import SourceConfig


class OfficialHttpClient:
    def __init__(self, config: SourceConfig) -> None:
        self.config = config
        self.client = httpx.Client(timeout=20, follow_redirects=True, headers={"User-Agent": "OpportunityRadar/0.1 (+policy research)"})

    def get(self, url: str) -> httpx.Response:
        hostname = urlparse(url).hostname or ""
        if hostname not in self.config.allowed_domains:
            raise ValueError(f"URL is not allow-listed: {hostname}")
        time.sleep(self.config.request_interval_seconds)
        response = self.client.get(url)
        if response.status_code in {401, 403, 429}:
            raise PermissionError(f"source access restricted: {response.status_code}")
        response.raise_for_status()
        return response
```

```python
# src/opportunity_radar/sources/base.py
from __future__ import annotations

import re
from datetime import date
from typing import Protocol
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from opportunity_radar.config import SourceConfig
from opportunity_radar.http import OfficialHttpClient
from opportunity_radar.models import PolicyCandidate

DATE = re.compile(r"(20\d{2})[-/.年](\d{1,2})[-/.月](\d{1,2})")


class PolicySource(Protocol):
    def discover(self, start: date, end: date) -> list[PolicyCandidate]: ...


class GenericHtmlSource:
    def __init__(self, config: SourceConfig, client: OfficialHttpClient) -> None:
        self.config, self.client = config, client

    def discover(self, start: date, end: date) -> list[PolicyCandidate]:
        found: dict[str, PolicyCandidate] = {}
        for list_url in self.config.list_urls:
            soup = BeautifulSoup(self.client.get(list_url).text, "html.parser")
            for anchor in soup.select("a[href]"):
                href, title = anchor.get("href", ""), anchor.get_text(" ", strip=True)
                if not href or len(title) < 8 or "政策" not in title and "通知" not in title and "办法" not in title:
                    continue
                detail_url = urljoin(list_url, href)
                if urlparse(detail_url).hostname not in self.config.allowed_domains:
                    continue
                candidate = PolicyCandidate(source_id=self.config.source_id, title=title, detail_url=detail_url)
                found[str(candidate.detail_url)] = candidate
        return list(found.values())
```

Create each of the six source modules as a thin named subclass so source-specific listing parsing can be introduced without changing the pipeline:

```python
# src/opportunity_radar/sources/miit.py
from opportunity_radar.sources.base import GenericHtmlSource


class MiitSource(GenericHtmlSource):
    pass
```

Repeat the same structure with classes `NdrcSource`, `ZhejiangHuiqiSource`, `ZhejiangEitSource`, `JiangsuGovernmentSource`, and `JiangsuEitSource`. In `registry.py`, map the six exact `source_id` values from `config/sources.json` to those classes.

```python
# src/opportunity_radar/sources/registry.py
from opportunity_radar.http import OfficialHttpClient
from opportunity_radar.sources.jiangsu_eit import JiangsuEitSource
from opportunity_radar.sources.jiangsu_government import JiangsuGovernmentSource
from opportunity_radar.sources.miit import MiitSource
from opportunity_radar.sources.ndrc import NdrcSource
from opportunity_radar.sources.zhejiang_eit import ZhejiangEitSource
from opportunity_radar.sources.zhejiang_huiqi import ZhejiangHuiqiSource

SOURCE_TYPES = {"miit": MiitSource, "ndrc": NdrcSource, "zhejiang_huiqi": ZhejiangHuiqiSource, "zhejiang_eit": ZhejiangEitSource, "jiangsu_government": JiangsuGovernmentSource, "jiangsu_eit": JiangsuEitSource}


def build_sources(configs):
    return {source_id: SOURCE_TYPES[source_id](config, OfficialHttpClient(config)) for source_id, config in configs.items() if config.enabled}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/sources -v`

Expected: PASS.

- [ ] **Step 5: Commit source access boundaries**

```bash
git add src/opportunity_radar/http.py src/opportunity_radar/sources tests/sources tests/fixtures/listing.html
git commit -m "feat: add official policy source adapters"
```

## Task 5: Parse policy pages and attachments into normalized, traceable documents

**Files:**

- Create: `src/opportunity_radar/parsing/html.py`
- Create: `src/opportunity_radar/parsing/attachments.py`
- Create: `tests/parsing/test_html.py`
- Create: `tests/parsing/test_attachments.py`
- Create: `tests/fixtures/policy.html`

**Interfaces:**

- Consumes a `PolicyCandidate`, an HTTP response, and optional downloaded attachments.
- Produces `parse_html(candidate, config, html, collected_at, snapshot_path) -> PolicyDocument`, `extract_attachment_text(content_type: str, body: bytes) -> str`, and `DocumentRetriever.fetch_document(source: GenericHtmlSource, candidate: PolicyCandidate, collected_at: datetime, raw_dir: Path) -> PolicyDocument`.

- [ ] **Step 1: Write failing parser tests**

```python
# tests/parsing/test_html.py
from datetime import datetime, timezone
from pathlib import Path

from opportunity_radar.config import SourceConfig
from opportunity_radar.models import PolicyCandidate
from opportunity_radar.parsing.html import parse_html


def test_parse_html_extracts_title_date_number_and_body() -> None:
    candidate = PolicyCandidate(source_id="miit", title="候选标题", detail_url="https://www.miit.gov.cn/art/1.html")
    document = parse_html(candidate, SourceConfig("miit", "工信部", "全国", (), ("www.miit.gov.cn",)), '<h1>设备更新通知</h1><p>工信部联装〔2026〕1号</p><p>发布时间：2026-07-20</p><article>支持制造业设备更新和技术改造。</article>', datetime.now(timezone.utc), Path("data/raw/x.html"))
    assert document.title == "设备更新通知"
    assert document.document_number == "工信部联装〔2026〕1号"
    assert document.publish_date.isoformat() == "2026-07-20"
    assert "技术改造" in document.normalized_text
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/parsing -v`

Expected: FAIL because parser modules are absent.

- [ ] **Step 3: Implement HTML and attachment extraction**

```python
# src/opportunity_radar/parsing/html.py
from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

from bs4 import BeautifulSoup

from opportunity_radar.config import SourceConfig
from opportunity_radar.models import PolicyCandidate, PolicyDocument
from opportunity_radar.normalization import content_hash, make_policy_id, normalize_text


def parse_html(candidate: PolicyCandidate, config: SourceConfig, html: str, collected_at: datetime, snapshot_path: Path) -> PolicyDocument:
    soup = BeautifulSoup(html, "html.parser")
    title = soup.find("h1").get_text(" ", strip=True) if soup.find("h1") else candidate.title
    body_node = soup.find("article") or soup.find("main") or soup.body or soup
    text = normalize_text(body_node.get_text(" ", strip=True))
    date_match = re.search(r"(20\d{2})[-年](\d{1,2})[-月](\d{1,2})", text)
    number_match = re.search(r"[\u4e00-\u9fff]+(?:〔|\[)20\d{2}(?:〕|\])\d+号", text)
    attachment_urls = [str(anchor["href"]) for anchor in soup.select("a[href$='.pdf'],a[href$='.doc'],a[href$='.docx']")]
    from datetime import date
    publish_date = date(*map(int, date_match.groups())) if date_match else candidate.published_at
    return PolicyDocument(policy_id=make_policy_id(candidate), source_id=config.source_id, source_name=config.display_name, region=config.region, title=title, detail_url=candidate.detail_url, document_number=number_match.group(0) if number_match else None, publish_date=publish_date, raw_text=text, normalized_text=text, attachment_urls=attachment_urls, collected_at=collected_at, content_hash=content_hash(text), snapshot_path=str(snapshot_path))
```

```python
# src/opportunity_radar/parsing/attachments.py
from io import BytesIO
from docx import Document
from pypdf import PdfReader


def extract_attachment_text(content_type: str, body: bytes) -> str:
    if "pdf" in content_type:
        return "\n".join(page.extract_text() or "" for page in PdfReader(BytesIO(body)).pages).strip()
    if "word" in content_type or "docx" in content_type:
        return "\n".join(paragraph.text for paragraph in Document(BytesIO(body)).paragraphs).strip()
    raise ValueError(f"unsupported attachment content type: {content_type}")
```

```python
# append to src/opportunity_radar/parsing/html.py
from opportunity_radar.parsing.snapshot import save_snapshot
from opportunity_radar.sources.base import GenericHtmlSource


class DocumentRetriever:
    def fetch_document(
        self, source: GenericHtmlSource, candidate: PolicyCandidate, collected_at: datetime, raw_dir: Path
    ) -> PolicyDocument:
        response = source.client.get(str(candidate.detail_url))
        snapshot = save_snapshot(raw_dir, make_policy_id(candidate), "html", response.content)
        return parse_html(candidate, source.config, response.text, collected_at, snapshot)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/parsing -v`

Expected: PASS.

- [ ] **Step 5: Commit parser behavior**

```bash
git add src/opportunity_radar/parsing tests/parsing tests/fixtures/policy.html
git commit -m "feat: parse policy pages and attachments"
```

## Task 6: Add schema-constrained AI policy analysis with a test double

**Files:**

- Create: `src/opportunity_radar/analysis/prompts.py`
- Create: `src/opportunity_radar/analysis/client.py`
- Create: `tests/analysis/test_client.py`

**Interfaces:**

- Produces `Analyzer.analyze(document: PolicyDocument, valid_codes: set[str], business_tags: list[str]) -> PolicyAnalysis`.
- Production implementation is `OpenAICompatibleAnalyzer`; tests use `StaticAnalyzer`.

- [ ] **Step 1: Write failing AI validation tests**

```python
# tests/analysis/test_client.py
from opportunity_radar.analysis.client import validate_analysis
from opportunity_radar.models import PolicyAnalysis


def test_validate_analysis_rejects_industry_code_not_in_local_table() -> None:
    analysis = PolicyAnalysis.model_validate({"is_benefit_policy": True, "summary": "设备更新", "support_direction": "更新", "opportunities": [{"section_code": "C", "section_name": "制造业", "division_code": "Z99", "division_name": "虚构行业", "business_tags": ["节能环保"], "confidence": 0.8, "scenarios": ["设备更新"], "evidence": [{"quote": "支持设备更新", "location": "第1段"}], "leasing_relevance": "高", "recommended_action": "联系", "opening_script": "您好，近期政策支持设备更新。"}]})
    assert validate_analysis(analysis, {"C", "C34"}).opportunities == []
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/analysis/test_client.py -v`

Expected: FAIL because analysis modules are absent.

- [ ] **Step 3: Implement the prompt, client, and local code validation**

```python
# src/opportunity_radar/analysis/prompts.py
SYSTEM_PROMPT = """你是政策商机分析助手。只依据提供的政策正文，不得编造文号、日期、补贴、企业事实或政策资格。每条行业机会必须给出不超过240字的原文短摘录和定位。禁止承诺补贴获得、融资审批或政府背书。只输出与给定 JSON Schema 匹配的 JSON。"""


def build_user_prompt(document_text: str, valid_codes: set[str], business_tags: list[str]) -> str:
    return f"政策正文：\n{document_text}\n\n允许行业代码：{sorted(valid_codes)}\n允许业务标签：{business_tags}"
```

```python
# src/opportunity_radar/analysis/client.py
from __future__ import annotations

import json
from typing import Protocol

import httpx

from opportunity_radar.analysis.prompts import SYSTEM_PROMPT, build_user_prompt
from opportunity_radar.models import PolicyAnalysis, PolicyDocument


class Analyzer(Protocol):
    def analyze(self, document: PolicyDocument, valid_codes: set[str], business_tags: list[str]) -> PolicyAnalysis: ...


class StaticAnalyzer:
    def __init__(self, analysis: PolicyAnalysis) -> None:
        self.analysis = analysis

    def analyze(self, document: PolicyDocument, valid_codes: set[str], business_tags: list[str]) -> PolicyAnalysis:
        return validate_analysis(self.analysis, valid_codes)


class OpenAICompatibleAnalyzer:
    def __init__(self, base_url: str, api_key: str, model: str) -> None:
        self.base_url, self.api_key, self.model = base_url.rstrip("/"), api_key, model

    def analyze(self, document: PolicyDocument, valid_codes: set[str], business_tags: list[str]) -> PolicyAnalysis:
        response = httpx.post(f"{self.base_url}/chat/completions", headers={"Authorization": f"Bearer {self.api_key}"}, json={"model": self.model, "response_format": {"type": "json_object"}, "messages": [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": build_user_prompt(document.normalized_text, valid_codes, business_tags)}]}, timeout=60)
        response.raise_for_status()
        content = response.json()["choices"][0]["message"]["content"]
        return validate_analysis(PolicyAnalysis.model_validate(json.loads(content)), valid_codes)


def validate_analysis(analysis: PolicyAnalysis, valid_codes: set[str]) -> PolicyAnalysis:
    kept = [item for item in analysis.opportunities if item.section_code in valid_codes and item.division_code in valid_codes]
    return analysis.model_copy(update={"opportunities": kept})
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `pytest tests/analysis/test_client.py -v`

Expected: PASS.

- [ ] **Step 5: Commit AI boundary and code validation**

```bash
git add src/opportunity_radar/analysis tests/analysis
git commit -m "feat: add schema constrained policy analysis"
```

## Task 7: Implement scoring, hard quality gates, and compliant opening scripts

**Files:**

- Create: `src/opportunity_radar/quality/scoring.py`
- Create: `src/opportunity_radar/quality/validation.py`
- Create: `src/opportunity_radar/quality/scripts.py`
- Create: `tests/quality/test_scoring.py`
- Create: `tests/quality/test_validation.py`

**Interfaces:**

- Produces `QualityResult(score: int, grade: str, sheet_name: str, review_reason: str | None)` and `evaluate(document: PolicyDocument, opportunity: IndustryOpportunity) -> QualityResult`.

- [ ] **Step 1: Write failing quality tests**

```python
# tests/quality/test_validation.py
from opportunity_radar.quality.scripts import is_compliant_script


def test_script_rejects_approval_and_subsidy_promises() -> None:
    assert is_compliant_script("我们保证您一定获得补贴并审批通过") is False
    assert is_compliant_script("我们可以交流近期设备更新安排") is True
```

```python
# tests/quality/test_scoring.py
from opportunity_radar.quality.scoring import QualityResult, evaluate_score, leasing_strength, support_strength
from opportunity_radar.quality.scripts import append_disclaimer
from opportunity_radar.quality.validation import opportunity_review_reason


def test_missing_evidence_always_routes_to_observation() -> None:
    result = evaluate_score(source_complete=True, evidence_complete=False, timely=True, industry_clear=True, support_strength=15, leasing_strength=30, actionable=True)
    assert result.sheet_name == "政策观察"
    assert result.review_reason == "缺少可定位的行业原文依据"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/quality -v`

Expected: FAIL because the quality modules are absent.

- [ ] **Step 3: Implement scoring and compliance gates**

```python
# src/opportunity_radar/quality/scoring.py
from dataclasses import dataclass


@dataclass(frozen=True)
class QualityResult:
    score: int
    grade: str
    sheet_name: str
    review_reason: str | None = None


def evaluate_score(*, source_complete: bool, evidence_complete: bool, timely: bool, industry_clear: bool, support_strength: int, leasing_strength: int, actionable: bool) -> QualityResult:
    if not evidence_complete:
        return QualityResult(0, "观察", "政策观察", "缺少可定位的行业原文依据")
    score = (15 if source_complete else 0) + (10 if timely else 0) + (20 if industry_clear else 0) + max(0, min(support_strength, 15)) + max(0, min(leasing_strength, 30)) + (10 if actionable else 0)
    grade = "A" if score >= 80 else "B" if score >= 60 else "C" if score >= 40 else "观察"
    return QualityResult(score, grade, "重点商机" if grade in {"A", "B"} else "政策观察")


def support_strength(text: str) -> int:
    return 15 if any(term in text for term in ("补贴", "奖励", "贴息", "专项资金")) else 8 if any(term in text for term in ("支持", "试点", "培育")) else 3


def leasing_strength(scenarios: list[str]) -> int:
    joined = " ".join(scenarios)
    return 30 if any(term in joined for term in ("设备采购", "设备更新", "技术改造", "扩产", "生产线", "车辆")) else 15 if any(term in joined for term in ("数字化", "节能", "绿色")) else 5
```

```python
# src/opportunity_radar/quality/scripts.py
FORBIDDEN = ("保证", "包过", "肯定到账", "一定获得", "一定获批", "政府背书")


def is_compliant_script(script: str) -> bool:
    return bool(script.strip()) and not any(phrase in script for phrase in FORBIDDEN)


def append_disclaimer(script: str) -> str:
    return f"{script.strip()}\n\n政策解读仅供业务参考，以政策原文及主管部门解释为准；融资方案及审批结果以正式评估为准。"
```

```python
# src/opportunity_radar/quality/validation.py
from opportunity_radar.models import IndustryOpportunity
from opportunity_radar.quality.scripts import is_compliant_script


def opportunity_review_reason(opportunity: IndustryOpportunity) -> str | None:
    if not opportunity.evidence:
        return "缺少可定位的行业原文依据"
    if not is_compliant_script(opportunity.opening_script):
        return "营销话术含过度承诺或政府背书表达"
    return None
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/quality -v`

Expected: PASS.

- [ ] **Step 5: Commit quality rules**

```bash
git add src/opportunity_radar/quality tests/quality
git commit -m "feat: add opportunity scoring and compliance gates"
```

## Task 8: Build a two-sheet Excel exporter and machine-readable run report

**Files:**

- Create: `src/opportunity_radar/export/excel.py`
- Create: `src/opportunity_radar/export/report.py`
- Create: `tests/export/test_excel.py`
- Create: `tests/export/test_report.py`

**Interfaces:**

- Produces `export_workbook(rows: list[ExportRow], output_dir: Path, run_date: date) -> Path` and `write_report(report: RunReport, output_dir: Path, run_date: date) -> Path`.

- [ ] **Step 1: Write failing export tests**

```python
# tests/export/test_excel.py
from datetime import date
from pathlib import Path

from openpyxl import load_workbook
from opportunity_radar.export.excel import ExportRow, export_workbook


def test_export_has_two_required_sheets_and_preserves_existing_file(tmp_path: Path) -> None:
    row = ExportRow("重点商机", {"商机等级": "A", "商机评分": 88, "政策名称": "设备更新通知", "国标行业大类代码": "C34", "国标行业大类名称": "通用设备制造业", "业务行业标签": "通用装备制造", "机会场景": "设备更新", "政策原文依据": "支持设备更新", "行业营销开场白": "交流设备更新安排", "政策原文链接": "https://example.gov.cn/policy"})
    first = export_workbook([row], tmp_path, date(2026, 7, 29))
    second = export_workbook([row], tmp_path, date(2026, 7, 29))
    assert first != second
    assert load_workbook(first).sheetnames == ["重点商机", "政策观察"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/export -v`

Expected: FAIL because exporter modules are absent.

- [ ] **Step 3: Implement row contract and workbook export**

```python
# src/opportunity_radar/export/excel.py
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill

HEADERS = ["商机等级", "商机评分", "政策名称", "政策摘要", "政策层级", "适用地区", "发布机构", "政策文号", "发布日期", "申报开始日期", "申报截止日期", "支持方向", "适用企业条件", "国标行业门类名称", "国标行业门类代码", "国标行业大类名称", "国标行业大类代码", "业务行业标签", "行业判断置信度", "机会场景", "融资租赁关联度", "推荐理由", "评分理由", "政策原文依据", "依据位置", "推荐动作", "推荐联系时间", "行业营销开场白", "风险与限制", "复核原因", "政策原文链接", "附件链接", "数据来源", "采集时间", "AI 分析时间", "免责声明"]


@dataclass(frozen=True)
class ExportRow:
    sheet_name: str
    values: dict[str, str | int | float]


def export_workbook(rows: list[ExportRow], output_dir: Path, run_date: date) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"policy-opportunities-{run_date.isoformat()}.xlsx"
    if path.exists():
        path = output_dir / f"policy-opportunities-{run_date.isoformat()}-{datetime.now().strftime('%H%M%S')}.xlsx"
    workbook = Workbook()
    workbook.remove(workbook.active)
    for sheet_name in ("重点商机", "政策观察"):
        sheet = workbook.create_sheet(sheet_name)
        sheet.append(HEADERS)
        for cell in sheet[1]:
            cell.font = Font(bold=True)
            cell.fill = PatternFill("solid", fgColor="D9EAF7")
        sheet.freeze_panes = "A2"
        sheet.auto_filter.ref = "A1:K1"
        for row in [item for item in rows if item.sheet_name == sheet_name]:
            sheet.append([row.values.get(header, "") for header in HEADERS])
            source_url = str(row.values.get("政策原文链接", ""))
            if source_url:
                sheet.cell(sheet.max_row, HEADERS.index("政策原文链接") + 1).hyperlink = source_url
        for column in sheet.columns:
            sheet.column_dimensions[column[0].column_letter].width = 20
    workbook.save(path)
    return path
```

```python
# src/opportunity_radar/export/report.py
import json
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path


@dataclass(frozen=True)
class RunReport:
    discovered: int = 0; changed: int = 0; skipped: int = 0; source_failures: int = 0; parse_failures: int = 0; analysis_failures: int = 0; priority_rows: int = 0; observation_rows: int = 0


def write_report(report: RunReport, output_dir: Path, run_date: date) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"policy-opportunities-{run_date.isoformat()}-report.json"
    path.write_text(json.dumps(asdict(report), ensure_ascii=False, indent=2), encoding="utf-8")
    return path
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/export -v`

Expected: PASS.

- [ ] **Step 5: Commit business outputs**

```bash
git add src/opportunity_radar/export tests/export
git commit -m "feat: export policy opportunities to excel"
```

## Task 9: Orchestrate the pipeline and expose a manual CLI command

**Files:**

- Create: `src/opportunity_radar/pipeline.py`
- Create: `src/opportunity_radar/cli.py`
- Create: `tests/test_pipeline.py`
- Modify: `README.md`

**Interfaces:**

- Produces `run_pipeline(config: RunConfig, sources: dict[str, PolicySource], retriever: DocumentRetriever, analyzer: Analyzer, valid_codes: set[str], business_tags: list[str]) -> tuple[Path, Path]`.
- Produces CLI command `opportunity-radar run --start-date YYYY-MM-DD --end-date YYYY-MM-DD --sources miit,ndrc`.

- [ ] **Step 1: Write the failing pipeline test**

```python
# tests/test_pipeline.py
from datetime import date
from pathlib import Path

from opportunity_radar.config import RunConfig
from opportunity_radar.pipeline import run_pipeline


def test_pipeline_exports_when_one_source_fails(tmp_path: Path, fake_sources, fake_retriever, static_analyzer) -> None:
    config = RunConfig(date(2026, 7, 1), date(2026, 7, 30), ("good", "bad"), tmp_path, tmp_path / "state.sqlite3", tmp_path / "raw", tmp_path / "normalized")
    workbook, report = run_pipeline(config, fake_sources, fake_retriever, static_analyzer, {"C", "C34"}, ["通用装备制造"])
    assert workbook.exists()
    assert '"source_failures": 1' in report.read_text(encoding="utf-8")
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/test_pipeline.py -v`

Expected: FAIL because the pipeline does not exist.

- [ ] **Step 3: Implement orchestration with source-level isolation**

```python
# src/opportunity_radar/pipeline.py
from __future__ import annotations

from datetime import datetime, timezone

from opportunity_radar.analysis.client import Analyzer
from opportunity_radar.config import RunConfig
from opportunity_radar.export.excel import ExportRow, export_workbook
from opportunity_radar.export.report import RunReport, write_report
from opportunity_radar.parsing.html import DocumentRetriever
from opportunity_radar.quality.scoring import QualityResult, evaluate_score, leasing_strength, support_strength
from opportunity_radar.quality.scripts import append_disclaimer
from opportunity_radar.quality.validation import opportunity_review_reason
from opportunity_radar.state import StateStore


def run_pipeline(config: RunConfig, sources, retriever: DocumentRetriever, analyzer: Analyzer, valid_codes: set[str], business_tags: list[str]):
    report = RunReport()
    rows: list[ExportRow] = []
    store = StateStore(config.state_path)
    for source_id in config.source_ids:
        try:
            candidates = sources[source_id].discover(config.start_date, config.end_date)
        except Exception:
            report = RunReport(**{**report.__dict__, "source_failures": report.source_failures + 1})
            continue
        for candidate in candidates:
            # Task 5's detail retrieval and parser are called here; keep candidate failures isolated.
            try:
                document = retriever.fetch_document(sources[source_id], candidate, datetime.now(timezone.utc), config.raw_dir)
                if document.publish_date and not config.start_date <= document.publish_date <= config.end_date:
                    continue
                if not store.is_changed(document.policy_id, document.content_hash):
                    report = RunReport(**{**report.__dict__, "skipped": report.skipped + 1})
                    continue
                analysis = analyzer.analyze(document, valid_codes, business_tags)
                if analysis.is_benefit_policy and not analysis.opportunities:
                    rows.append(ExportRow("政策观察", {"商机等级": "观察", "政策名称": document.title, "政策摘要": analysis.summary, "适用地区": document.region, "支持方向": analysis.support_direction, "复核原因": "惠企政策未识别到可验证的机会行业", "政策原文链接": str(document.detail_url), "数据来源": document.source_name, "采集时间": document.collected_at.isoformat()}))
                for opportunity in analysis.opportunities:
                    review_reason = opportunity_review_reason(opportunity)
                    quality = QualityResult(0, "观察", "政策观察", review_reason) if review_reason else evaluate_score(source_complete=bool(document.publisher or document.source_name), evidence_complete=bool(opportunity.evidence), timely=document.application_end_date is None or document.application_end_date >= config.end_date, industry_clear=opportunity.confidence >= 0.7, support_strength=support_strength(analysis.support_direction), leasing_strength=leasing_strength(opportunity.scenarios), actionable=bool(opportunity.recommended_action))
                    rows.append(ExportRow(quality.sheet_name, {"商机等级": quality.grade, "商机评分": quality.score, "政策名称": document.title, "适用地区": document.region, "国标行业大类代码": opportunity.division_code, "国标行业大类名称": opportunity.division_name, "业务行业标签": "、".join(opportunity.business_tags), "行业判断置信度": opportunity.confidence, "机会场景": "、".join(opportunity.scenarios), "融资租赁关联度": opportunity.leasing_relevance, "政策原文依据": opportunity.evidence[0].quote, "依据位置": opportunity.evidence[0].location, "推荐动作": opportunity.recommended_action, "行业营销开场白": append_disclaimer(opportunity.opening_script), "复核原因": quality.review_reason or "", "政策原文链接": str(document.detail_url), "数据来源": document.source_name, "采集时间": document.collected_at.isoformat(), "免责声明": "政策解读仅供业务参考，以政策原文及主管部门解释为准；融资方案及审批结果以正式评估为准。"}))
                store.record_success(document.policy_id, document.content_hash)
            except Exception:
                report = RunReport(**{**report.__dict__, "analysis_failures": report.analysis_failures + 1})
    workbook = export_workbook(rows, config.output_dir, config.end_date)
    priority_rows = sum(row.sheet_name == "重点商机" for row in rows)
    completed = RunReport(**{**report.__dict__, "priority_rows": priority_rows, "observation_rows": len(rows) - priority_rows})
    return workbook, write_report(completed, config.output_dir, config.end_date)
```

```python
# src/opportunity_radar/cli.py
from __future__ import annotations

import argparse
import json
import os
from datetime import date
from pathlib import Path

from opportunity_radar.analysis.client import OpenAICompatibleAnalyzer
from opportunity_radar.config import RunConfig, load_sources
from opportunity_radar.industry import load_industry_codes
from opportunity_radar.parsing.html import DocumentRetriever
from opportunity_radar.pipeline import run_pipeline
from opportunity_radar.sources.registry import build_sources


def main() -> None:
    parser = argparse.ArgumentParser(prog="opportunity-radar")
    subcommands = parser.add_subparsers(dest="command", required=True)
    run = subcommands.add_parser("run")
    run.add_argument("--start-date")
    run.add_argument("--end-date")
    run.add_argument("--sources", default="miit,ndrc,zhejiang_huiqi,zhejiang_eit,jiangsu_government,jiangsu_eit")
    args = parser.parse_args()
    if args.command == "run":
        config = RunConfig.from_optional_dates(date.fromisoformat(args.start_date) if args.start_date else None, date.fromisoformat(args.end_date) if args.end_date else None, tuple(args.sources.split(",")))
        configured = load_sources(Path("config/sources.json"))
        sources = build_sources({source_id: configured[source_id] for source_id in config.source_ids})
        analyzer = OpenAICompatibleAnalyzer(os.getenv("OPPORTUNITY_RADAR_LLM_BASE_URL", "https://api.openai.com/v1"), os.environ["OPPORTUNITY_RADAR_LLM_API_KEY"], os.environ["OPPORTUNITY_RADAR_LLM_MODEL"])
        valid_codes = load_industry_codes(Path("data/industry/gbt_4754_2017.json"))
        business_tags = json.loads(Path("config/business_industries.json").read_text(encoding="utf-8"))
        workbook, report = run_pipeline(config, sources, DocumentRetriever(), analyzer, valid_codes, business_tags)
        print(f"Workbook: {workbook}\nReport: {report}")
```

Document the exact manual command in `README.md`:

```bash
uv sync --extra dev
opportunity-radar run --start-date 2026-06-29 --end-date 2026-07-29 --sources miit,ndrc,zhejiang_huiqi,zhejiang_eit,jiangsu_government,jiangsu_eit
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `pytest tests/test_pipeline.py -v`

Expected: PASS; a source exception is recorded and the workbook/report are still created.

- [ ] **Step 5: Commit orchestration and operator documentation**

```bash
git add src/opportunity_radar/pipeline.py src/opportunity_radar/cli.py tests/test_pipeline.py README.md
git commit -m "feat: add manual policy radar pipeline"
```

## Task 10: Validate the complete local workflow against fixtures and real-source smoke checks

**Files:**

- Modify: `tests/conftest.py`
- Modify: `tests/test_pipeline.py`
- Modify: `README.md`
- Create: `docs/operations/policy-source-smoke-check.md`

**Interfaces:**

- Consumes the complete pipeline from Task 9.
- Produces a repeatable local fixture run and a documented, non-destructive live-source smoke-check procedure.

- [ ] **Step 1: Write failing end-to-end fixture test**

```python
# tests/test_pipeline.py
def test_fixture_run_writes_priority_and_observation_rows(tmp_path, fixture_sources, fixture_retriever, fixture_analyzer):
    config = RunConfig(date(2026, 7, 1), date(2026, 7, 30), ("fixture",), tmp_path, tmp_path / "state.sqlite3", tmp_path / "raw", tmp_path / "normalized")
    workbook, report = run_pipeline(config, fixture_sources, fixture_retriever, fixture_analyzer, {"C", "C34"}, ["通用装备制造"])
    from openpyxl import load_workbook
    book = load_workbook(workbook)
    assert book["重点商机"].max_row == 2
    assert book["政策观察"].max_row == 2
    assert '"analysis_failures": 0' in report.read_text(encoding="utf-8")
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/test_pipeline.py::test_fixture_run_writes_priority_and_observation_rows -v`

Expected: FAIL until the fixture retriever, static analyses, and quality routing are all wired together.

- [ ] **Step 3: Implement fixtures and smoke-check documentation**

Create `tests/conftest.py` fixtures that supply:

```python
@pytest.fixture
def fixture_sources():
    return {"fixture": FixtureSource(two_policy_documents_with_distinct_evidence=True)}


@pytest.fixture
def fixture_analyzer():
    return MappingAnalyzer({"priority-policy": priority_analysis, "observation-policy": observation_analysis})
```

Create `docs/operations/policy-source-smoke-check.md` with this exact operator procedure:

```text
1. Run only one official source and a one-day range.
2. Confirm the source returns public content without login, CAPTCHA, 403, or 429 responses.
3. Confirm output rows preserve source URLs and the saved snapshot is readable.
4. If a source is restricted, set its `enabled` flag to false in config/sources.json; do not change headers, automate a browser, or retry aggressively.
5. Record page structure changes with the source ID, URL, date, and a redacted HTML fixture before changing that adapter.
```

Add the full verification commands to `README.md`:

```bash
pytest -q
ruff check src tests scripts
opportunity-radar run --start-date 2026-07-01 --end-date 2026-07-02 --sources miit
```

- [ ] **Step 4: Run the full test suite and static checks**

Run: `pytest -q && ruff check src tests scripts`

Expected: all tests PASS and Ruff reports no violations.

- [ ] **Step 5: Perform a safe live smoke check and commit**

Run: `opportunity-radar run --start-date 2026-07-01 --end-date 2026-07-02 --sources miit`

Expected: an Excel workbook and JSON report are created; any 403/429 is recorded as a source failure without bypassing access controls.

```bash
git add tests README.md docs/operations/policy-source-smoke-check.md
git commit -m "test: verify policy radar end to end"
```

## Plan Self-Review

### Spec coverage

| Requirement | Implementing tasks |
|---|---|
| Manual Codex/WorkBuddy/terminal operation and configurable dates | Tasks 1 and 9 |
| National, Zhejiang, and Jiangsu official sources | Tasks 1 and 4 |
| Low-frequency, allow-listed, non-circumventing collection | Task 4 and Task 10 |
| HTML, PDF, and Word parsing with snapshots | Tasks 3 and 5 |
| Incremental deduplication and policy updates | Task 3 and Task 9 |
| AI policy interpretation, dual industry classification, evidence, and scripts | Tasks 2 and 6 |
| GB/T 4754 code validation | Task 2 and Task 6 |
| Scoring, two-sheet routing, and compliance gates | Task 7 and Task 8 |
| Traceable Excel and run report | Task 8 |
| Source/parse/AI failure isolation and output preservation | Tasks 4, 5, 8, and 9 |
| Automated tests, business-quality fixtures, and live smoke procedure | Task 10 |

### Consistency checks completed

- All later tasks use the models, `RunConfig`, `Analyzer`, `QualityResult`, and exporter contracts introduced in earlier tasks.
- The only final business workbook sheets are `重点商机` and `政策观察`.
- Evidence is a hard gate for `重点商机` in both the plan constraints and Task 7 tests.
- No task adds enterprise matching, a web UI, scheduling, personal-data collection, or an access-control bypass.
