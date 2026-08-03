import json
from unittest.mock import MagicMock

from opportunity_radar.compliance import load_compliance_sources
from opportunity_radar.discovery.models import (
    CheckDetails,
    ComplianceReport,
    CrawlResult,
    ScoreResult,
)
from opportunity_radar.discovery.orchestrator import DiscoveryOrchestrator


def _crawl_result(restricted=False, reason=None, items=None):
    return CrawlResult(fetch_mode="http", html="<a>通知</a>", text_content="设备更新融资租赁",
                       page_title="t", policy_items=items or [],
                       snapshot_path="s.html", final_url="https://www.gov.cn/zc/",
                       restricted=restricted, restricted_reason=reason)


def _report(check_result="pass"):
    return ComplianceReport(check_result=check_result,
        check_details=CheckDetails(domain_owner="gov", accessibility={"public": True},
            login_required=False, captcha_triggered=False, robots={"allowed": True, "raw": ""},
            rate_limit_hints={}, column_structure={"sample_count": 3}), recommendation="建议启用")


def _score(total=85):
    return ScoreResult(priority_score=total, priority_level="高" if total >= 80 else "中", score_breakdown=[])


def test_orchestrator_writes_candidate_and_report(tmp_path, monkeypatch):
    from opportunity_radar.discovery.models import PolicyItem
    portal = [{"portal_id": "gov", "display_name": "国务院", "region": "国家",
               "entry_url": "https://www.gov.cn/zc/index.html", "admin_level": "国家", "gov_domain": "www.gov.cn"}]
    monkeypatch.setattr("opportunity_radar.discovery.orchestrator.load_portal_seeds", lambda: portal)

    crawler = MagicMock()
    crawler.crawl.return_value = _crawl_result(
        items=[PolicyItem(title="设备更新通知", url="https://www.gov.cn/p/1")])
    checker = MagicMock(); checker.check.return_value = _report()
    scorer = MagicMock(); scorer.score.return_value = _score(95)
    kws = MagicMock(); kws.get_search_keywords.return_value = []

    comp_path = tmp_path / "compliance.json"; comp_path.write_text("[]")
    rep_dir = tmp_path / "reports"
    orch = DiscoveryOrchestrator(crawler, checker, scorer, kws,
                                 compliance_path=str(comp_path), report_dir=str(rep_dir))
    report = orch.run(keyword_tags=None, portal_ids=None)

    assert report.candidates == ["gov"]
    written = json.loads(comp_path.read_text())
    assert written[0]["origin"] == "discovery"
    assert written[0]["phase"] == "candidate"
    assert written[0]["enabled"] is False
    assert written[0]["discovery"]["priority_score"] == 95
    assert (rep_dir / f"{report.job_id}-report.json").exists()


def test_orchestrator_restricted_portal_recorded_no_candidate(tmp_path, monkeypatch):
    portal = [{"portal_id": "gov2", "display_name": "X", "region": "国家",
               "entry_url": "https://x.gov.cn/z", "admin_level": "国家", "gov_domain": "x.gov.cn"}]
    monkeypatch.setattr("opportunity_radar.discovery.orchestrator.load_portal_seeds", lambda: portal)
    crawler = MagicMock(); crawler.crawl.return_value = _crawl_result(restricted=True, reason="captcha")
    orch = DiscoveryOrchestrator(crawler, MagicMock(), MagicMock(), MagicMock(),
                                 compliance_path=str(tmp_path / "c.json"), report_dir=str(tmp_path))
    report = orch.run(None, None)
    assert report.candidates == []
    assert report.stats["restricted_stopped"] == 1
    assert report.errors[0]["reason"] == "captcha"


def test_orchestrator_candidate_loadable_by_compliance(tmp_path, monkeypatch):
    """编排器产出的最小候选记录（8 字段 + discovery）可被 load_compliance_sources 加载。"""
    from opportunity_radar.discovery.models import PolicyItem

    portal = [{"portal_id": "gov", "display_name": "国务院", "region": "国家",
               "entry_url": "https://www.gov.cn/zc/index.html", "admin_level": "国家", "gov_domain": "www.gov.cn"}]
    monkeypatch.setattr("opportunity_radar.discovery.orchestrator.load_portal_seeds", lambda: portal)

    crawler = MagicMock()
    crawler.crawl.return_value = _crawl_result(
        items=[PolicyItem(title="设备更新通知", url="https://www.gov.cn/p/1")])
    checker = MagicMock(); checker.check.return_value = _report()
    scorer = MagicMock(); scorer.score.return_value = _score(95)
    kws = MagicMock(); kws.get_search_keywords.return_value = []

    comp_path = tmp_path / "compliance.json"; comp_path.write_text("[]")
    orch = DiscoveryOrchestrator(crawler, checker, scorer, kws,
                                 compliance_path=str(comp_path), report_dir=str(tmp_path / "reports"))
    orch.run(keyword_tags=None, portal_ids=None)

    sources = load_compliance_sources(comp_path)
    assert "gov" in sources
    src = sources["gov"]
    assert src.origin == "discovery"
    assert src.phase == "candidate"
    assert src.enabled is False
    assert src.discovery is not None
    assert src.discovery.priority_score == 95
    assert src.discovery.portal_seed_id == "gov"
