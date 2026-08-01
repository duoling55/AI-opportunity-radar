"""端到端集成验证（FR-15 Plan A 收尾）。

用真实组件（PortalCrawler/ComplianceChecker/ImportanceScorer/FallbackKeywordSource/
DiscoveryOrchestrator）贯通全链路，仅 mock HTTP。验证：
关键词 -> 门户抓取 -> 解析 -> 关键词匹配 -> 合规核查 -> 评分 -> 候选落库 -> 报告产出。
"""

import json

import httpx

from opportunity_radar.discovery.checker import ComplianceChecker
from opportunity_radar.discovery.crawler import PortalCrawler
from opportunity_radar.discovery.keywords import FallbackKeywordSource
from opportunity_radar.discovery.orchestrator import DiscoveryOrchestrator
from opportunity_radar.discovery.scorer import ImportanceScorer


def test_e2e_discovery_pipeline(httpx_mock, tmp_path, monkeypatch):
    portal = [
        {
            "portal_id": "gov_e2e",
            "display_name": "国务院",
            "region": "国家",
            "entry_url": "https://www.gov.cn/zc/index.html",
            "admin_level": "国家",
            "gov_domain": "www.gov.cn",
        }
    ]
    monkeypatch.setattr(
        "opportunity_radar.discovery.orchestrator.load_portal_seeds", lambda: portal
    )

    # 门户页被请求两次（crawler 抓取 + checker 可访问性探测），故 reusable。
    # robots.txt 被 checker 请求一次。
    httpx_mock.add_response(url="https://www.gov.cn/robots.txt", text="Allow: /")
    httpx_mock.add_response(
        url="https://www.gov.cn/zc/index.html",
        text='<a href="/p/1">关于设备融资租赁更新的通知</a>',
        is_reusable=True,
    )

    comp = tmp_path / "compliance.json"
    comp.write_text("[]")

    orch = DiscoveryOrchestrator(
        PortalCrawler(
            httpx.Client(timeout=10),
            request_interval=0.0,
            snapshots_dir=str(tmp_path / "snapshots"),
        ),
        ComplianceChecker(httpx.Client(timeout=10)),
        ImportanceScorer(),
        FallbackKeywordSource(path="config/discovery_keywords.json"),
        compliance_path=str(comp),
        report_dir=str(tmp_path),
    )
    report = orch.run(None, None)

    # 全链路贯通：1 个候选被产出并落库
    assert len(report.candidates) == 1
    assert report.candidates == ["gov_e2e"]
    assert report.stats["portals_scanned"] == 1
    assert report.stats["candidates_found"] == 1
    assert report.stats["restricted_stopped"] == 0

    written = json.loads(comp.read_text())
    assert len(written) == 1
    cand = written[0]
    assert cand["origin"] == "discovery"
    assert cand["phase"] == "candidate"
    assert cand["enabled"] is False
    assert cand["source_id"] == "gov_e2e"
    # 评分与核查字段已落库且类型合规
    assert cand["discovery"]["priority_score"] >= 0
    assert cand["discovery"]["check_result"] in (
        "pass",
        "needs_attention",
        "not_recommended",
    )
    # 关键词命中应包含融资租赁（种子词直接命中标题）
    assert "融资租赁" in cand["discovery"]["keywords"]

    # 报告文件已写出
    report_files = list(tmp_path.glob("*-report.json"))
    assert len(report_files) == 1
    rep = json.loads(report_files[0].read_text())
    assert rep["candidates"] == ["gov_e2e"]
