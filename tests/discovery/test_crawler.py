import httpx

from opportunity_radar.discovery.crawler import PortalCrawler


def _crawler(http: httpx.Client) -> PortalCrawler:
    return PortalCrawler(http=http, browser=None, request_interval=0.0)


def test_crawl_static_html_extracts_policy_links(httpx_mock):
    html = (
        '<html><head><title>政策列表</title></head><body>'
        '<a href="/p/1">关于设备更新的通知</a>'
        '<a href="/news/2">新闻动态</a>'
        '</body></html>'
    )
    httpx_mock.add_response(
        url="https://www.gov.cn/zc/index.html",
        text=html,
        headers={"Content-Type": "text/html"},
    )
    c = _crawler(httpx.Client())
    r = c.crawl("https://www.gov.cn/zc/index.html", "gov")
    assert r.fetch_mode == "http"
    assert r.page_title == "政策列表"
    assert len(r.policy_items) == 1
    assert r.policy_items[0].title == "关于设备更新的通知"
    assert r.policy_items[0].url == "https://www.gov.cn/p/1"
    assert r.restricted is False
    assert "设备更新" in r.text_content


def test_crawl_login_form_marks_restricted(httpx_mock):
    html = '<input type="password"><button>登录</button>'
    httpx_mock.add_response(url="https://www.gov.cn/secret.html", text=html)
    r = _crawler(httpx.Client()).crawl("https://www.gov.cn/secret.html", "gov")
    assert r.restricted is True
    assert r.restricted_reason == "login"


def test_crawl_captcha_marks_restricted(httpx_mock):
    html = '<body>请输入验证码继续访问</body>'
    httpx_mock.add_response(url="https://www.gov.cn/c.html", text=html)
    r = _crawler(httpx.Client()).crawl("https://www.gov.cn/c.html", "gov")
    assert r.restricted is True
    assert r.restricted_reason == "captcha"


def test_crawl_403_marks_restricted(httpx_mock):
    httpx_mock.add_response(url="https://www.gov.cn/x.html", status_code=403)
    r = _crawler(httpx.Client()).crawl("https://www.gov.cn/x.html", "gov")
    assert r.restricted is True
    assert r.restricted_reason == "http_403"


def test_crawl_cross_domain_final_url_restricted(httpx_mock):
    httpx_mock.add_response(
        url="https://www.gov.cn/redirect.html",
        status_code=302,
        headers={"Location": "https://evil.com/p"},
    )
    httpx_mock.add_response(url="https://evil.com/p", text="<a href='/a'>通知</a>")
    r = _crawler(httpx.Client()).crawl(
        "https://www.gov.cn/redirect.html", "gov", allowed_domains=("www.gov.cn",)
    )
    assert r.restricted is True
    assert r.restricted_reason == "cross_domain"
