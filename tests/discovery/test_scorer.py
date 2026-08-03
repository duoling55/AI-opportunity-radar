from opportunity_radar.discovery.models import CheckDetails, ComplianceReport
from opportunity_radar.discovery.scorer import ImportanceScorer


def _report(check_result="pass"):
    return ComplianceReport(check_result=check_result,
        check_details=CheckDetails(domain_owner="gov", accessibility={"public": True},
            login_required=False, captcha_triggered=False, robots={"allowed": True, "raw": ""},
            rate_limit_hints={}, column_structure={"sample_count": 5}),
        recommendation="建议启用")


def test_national_gov_lease_direct_high():
    src = {"admin_level": "国家", "domain": "www.gov.cn", "column_name": "融资租赁政策",
           "sample_policies": [{"title": "设备融资租赁通知", "url": "u"}, {"title": "绿色租赁办法", "url": "u"},
                               {"title": "技改通知", "url": "u"}]}
    r = ImportanceScorer().score(src, src["sample_policies"], _report())
    assert r.priority_score == 30 + 25 + 20 + 5 + 10 + 5  # 95
    assert r.priority_level == "高"
    dims = {b.dimension: b.score for b in r.score_breakdown}
    assert dims["行政层级"] == 30 and dims["行业相关性"] == 25 and dims["域名权威性"] == 5


def test_city_non_gov_low():
    src = {"admin_level": "市", "domain": "example.com", "column_name": "产业动态",
           "sample_policies": [{"title": "产业新闻", "url": "u"}]}
    r = ImportanceScorer().score(src, src["sample_policies"], _report("not_recommended"))
    assert r.priority_level == "低"
    dims = {b.dimension: b.score for b in r.score_breakdown}
    assert dims["行政层级"] == 10 and dims["合规可采集性"] == 0 and dims["域名权威性"] == 0


def test_insufficient_samples_uses_mid_frequency():
    src = {"admin_level": "省", "domain": "zj.gov.cn", "column_name": "通知",
           "sample_policies": [{"title": "通知", "url": "u"}]}
    r = ImportanceScorer().score(src, src["sample_policies"], _report("needs_attention"))
    freq = next(b for b in r.score_breakdown if b.dimension == "政策更新频率")
    assert freq.score == 5 and "样例不足" in freq.reason
