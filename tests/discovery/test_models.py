from datetime import date

from opportunity_radar.compliance import ComplianceSource
from opportunity_radar.config import SourceConfig
from opportunity_radar.discovery.models import (
    CheckDetails,
    CrawlResult,
    DiscoveryMeta,
    PolicyItem,
)


def _candidate_kwargs(**overrides):
    """Build required ComplianceSource fields for a candidate-phase source."""
    defaults = {
        "source_id": "gov_zc",
        "display_name": "国务院政策",
        "phase": "candidate",
        "enabled": False,
        "terms": "自动访问条款待确认。",
        "terms_confirmed": None,
        "registration": "unknown",
        "registration_completed": None,
        "authorization": "unknown",
        "rate_limit": None,
        "selected_data_scope": "unknown",
        "field_permission_confirmed": None,
        "evidence_url": "https://www.gov.cn/evidence",
        "verified_at": None,
        "review_due_at": date(2026, 10, 27),
        "owner": "unassigned",
        "available_fields": (),
    }
    defaults.update(overrides)
    return defaults


def test_compliance_source_accepts_origin_and_discovery():
    meta = DiscoveryMeta(
        keywords=["设备更新"],
        discovered_at=date(2026, 8, 1),
        portal_seed_id="gov",
        admin_level="国家",
        sample_policies=[],
        snapshots=["data/discovery/snapshots/gov/x.html"],
        check_result="pass",
        check_details=CheckDetails(
            domain_owner="gov",
            accessibility={"status_code": 200, "public": True},
            login_required=False,
            captcha_triggered=False,
            robots={"allowed": True, "raw": ""},
            rate_limit_hints={},
            column_structure={"list_page": True, "detail_page": True, "sample_count": 3},
        ),
        recommendation="建议启用",
        priority_score=85,
        priority_level="高",
        score_breakdown=[],
    )
    src = ComplianceSource(**_candidate_kwargs(origin="discovery", discovery=meta))
    assert src.origin == "discovery"
    assert src.discovery.priority_score == 85
    assert src.phase == "candidate"


def test_compliance_source_defaults_origin_manual():
    src = ComplianceSource(**_candidate_kwargs())
    assert src.origin == "manual"
    assert src.discovery is None


def test_source_config_defaults_origin_manual():
    sc = SourceConfig(
        source_id="x",
        display_name="X",
        region="全国",
        list_urls=("https://x.gov.cn",),
        allowed_domains=("x.gov.cn",),
    )
    assert sc.origin == "manual"


def test_crawl_result_roundtrips():
    r = CrawlResult(
        fetch_mode="http",
        html="<a>x</a>",
        text_content="x",
        page_title="t",
        policy_items=[PolicyItem(title="通知", url="https://x.gov.cn/p/1")],
        snapshot_path="s.html",
        final_url="https://x.gov.cn/",
        restricted=False,
    )
    assert r.policy_items[0].url.endswith("/p/1")
