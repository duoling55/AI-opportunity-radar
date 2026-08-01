from opportunity_radar.discovery.checker import ComplianceChecker
from opportunity_radar.discovery.models import CrawlResult


def _candidate(
    url="https://www.gov.cn/zc/index.html", domain="www.gov.cn", samples=None
):
    if samples is None:
        samples = [
            {"title": "通知一", "url": "https://www.gov.cn/p/1"},
            {"title": "通知二", "url": "https://www.gov.cn/p/2"},
            {"title": "通知三", "url": "https://www.gov.cn/p/3"},
        ]
    return {
        "url": url,
        "domain": domain,
        "sample_policies": samples,
        "scan_result": CrawlResult(
            fetch_mode="http",
            html="",
            text_content="",
            page_title="",
            policy_items=[],
            snapshot_path="",
            final_url=url,
            restricted=False,
        ),
    }


def test_gov_public_no_captcha_passes(httpx_mock):
    httpx_mock.add_response(
        url="https://www.gov.cn/robots.txt", text="User-agent: *\nAllow: /"
    )
    httpx_mock.add_response(
        url="https://www.gov.cn/zc/index.html", status_code=200, text="<html></html>"
    )
    r = ComplianceChecker().check(_candidate())
    assert r.check_result == "pass"
    assert r.recommendation == "建议启用"
    assert r.check_details.domain_owner == "gov"


def test_non_gov_domain_not_recommended(httpx_mock):
    httpx_mock.add_response(url="https://example.com/robots.txt", text="Allow: /")
    httpx_mock.add_response(
        url="https://example.com/x", status_code=200, text="<html></html>"
    )
    r = ComplianceChecker().check(_candidate(url="https://example.com/x", domain="example.com"))
    assert r.check_result == "not_recommended"
    assert r.check_details.domain_owner == "other"


def test_captcha_in_scan_result_not_recommended(httpx_mock):
    httpx_mock.add_response(url="https://www.gov.cn/robots.txt", text="Allow: /")
    httpx_mock.add_response(
        url="https://www.gov.cn/zc/index.html", status_code=200, text="<html></html>"
    )
    c = _candidate()
    c["scan_result"] = CrawlResult(
        fetch_mode="http",
        html="",
        text_content="",
        page_title="",
        policy_items=[],
        snapshot_path="",
        final_url=c["url"],
        restricted=True,
        restricted_reason="captcha",
    )
    r = ComplianceChecker().check(c)
    assert r.check_result == "not_recommended"


def test_robots_disallow_not_recommended(httpx_mock):
    httpx_mock.add_response(
        url="https://www.gov.cn/robots.txt", text="User-agent: *\nDisallow: /zc/"
    )
    httpx_mock.add_response(
        url="https://www.gov.cn/zc/index.html", status_code=200, text="<html></html>"
    )
    r = ComplianceChecker().check(_candidate(url="https://www.gov.cn/zc/index.html"))
    assert r.check_result == "not_recommended"


def test_low_sample_count_needs_attention(httpx_mock):
    httpx_mock.add_response(url="https://www.gov.cn/robots.txt", text="Allow: /")
    httpx_mock.add_response(
        url="https://www.gov.cn/zc/index.html", status_code=200, text="<html></html>"
    )
    samples = [{"title": "通知", "url": "https://www.gov.cn/p/1"}]  # 仅 1 条 < 3
    r = ComplianceChecker().check(_candidate(samples=samples))
    assert r.check_result == "needs_attention"
