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


def test_crawl_404_marks_restricted_and_skips_snapshot(httpx_mock, tmp_path):
    httpx_mock.add_response(url="https://www.gov.cn/missing.html", status_code=404)
    c = PortalCrawler(
        http=httpx.Client(),
        browser=None,
        request_interval=0.0,
        snapshots_dir=str(tmp_path),
    )
    r = c.crawl("https://www.gov.cn/missing.html", "gov_404")
    assert r.restricted is True
    assert r.restricted_reason == "http_404"
    assert r.snapshot_path == ""
    assert not (tmp_path / "gov_404").exists()


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


class _FakePage:
    def __init__(self, html: str, final_url: str) -> None:
        self._html = html
        self.url = final_url
        self.closed = False

    def goto(self, url, wait_until=None, timeout=None):
        return None

    def wait_for_timeout(self, ms):
        return None

    def content(self):
        return self._html

    def close(self):
        self.closed = True


class _FakeBrowser:
    def __init__(self, html: str, final_url: str) -> None:
        self._page = _FakePage(html, final_url)
        self.started = False

    def _ensure_started(self):
        self.started = True

    @property
    def _context(self):
        outer = self

        class _Ctx:
            def new_page(self):
                return outer._page

        return _Ctx()


def test_crawl_falls_back_to_browser_when_http_empty(httpx_mock):
    # HTTP 返回无政策链接的页面（模拟 JS 渲染页）
    httpx_mock.add_response(
        url="https://www.gov.cn/zc/index.html",
        text="<html><body>JS app</body></html>",
        headers={"Content-Type": "text/html"},
    )
    rendered = (
        '<html><head><title>政策列表</title></head><body>'
        '<a href="/p/1">关于设备更新的通知</a></body></html>'
    )
    browser = _FakeBrowser(rendered, "https://www.gov.cn/zc/index.html")
    c = PortalCrawler(http=httpx.Client(), browser=browser, request_interval=0.0)
    r = c.crawl("https://www.gov.cn/zc/index.html", "gov")
    assert browser.started is True
    assert r.fetch_mode == "playwright"
    assert len(r.policy_items) == 1
    assert r.policy_items[0].title == "关于设备更新的通知"
    assert r.restricted is False


def test_crawl_skips_browser_when_http_found_items(httpx_mock):
    html = '<a href="/p/1">关于设备更新的通知</a>'
    httpx_mock.add_response(url="https://www.gov.cn/zc/index.html", text=html)
    browser = _FakeBrowser("<a>不应被调用</a>", "https://www.gov.cn/zc/index.html")
    c = PortalCrawler(http=httpx.Client(), browser=browser, request_interval=0.0)
    r = c.crawl("https://www.gov.cn/zc/index.html", "gov")
    assert r.fetch_mode == "http"
    assert browser.started is False
