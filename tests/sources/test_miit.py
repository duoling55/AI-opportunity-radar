from datetime import date
from urllib.parse import urlencode

from opportunity_radar.config import SourceConfig
from opportunity_radar.http import OfficialHttpClient
from opportunity_radar.sources.miit import MiitSource


def test_miit_discovers_and_paginates_the_latest_policy_unit(httpx_mock) -> None:
    list_url = "https://www.miit.gov.cn/xwfb/zxzc/index.html"
    endpoint = (
        "https://www.miit.gov.cn/"
        "api-gateway/jpaas-publish-server/front/page/build/unit"
    )
    query = {"parseType": "buildstatic", "webId": "web-1"}
    landing = """
        <script
          url="/api-gateway/jpaas-publish-server/front/page/build/unit"
          queryData="{'parseType':'buildstatic','webId':'web-1'}"
        ></script>
    """
    first_page = """
        <div class="page-content">
          <ul>
            <li>
              <a
                href="/zwgk/zcwj/wjfb/tz/art/2026/first.html"
                title="智能工厂建设通知"
              >
                智能工厂建设...
              </a>
              <span>2026-07-28</span>
            </li>
          </ul>
        </div>
        <div class="pagination" rows="24" count="48" pageNo="1"></div>
    """
    second_page = """
        <div class="page-content">
          <ul>
            <li>
              <a href="/zwgk/zcwj/wjfb/gg/art/2026/second.html">
                工业和信息化部公告
              </a>
              <span>2026-06-15</span>
            </li>
          </ul>
        </div>
        <div class="pagination" rows="24" count="48" pageNo="2"></div>
    """
    httpx_mock.add_response(url=list_url, text=landing)
    httpx_mock.add_response(
        url=f"{endpoint}?{urlencode(query)}",
        json={"data": {"html": first_page}},
    )
    second_query = {
        **query,
        "paramJson": '{"pageNo":2,"pageSize":24}',
    }
    httpx_mock.add_response(
        url=f"{endpoint}?{urlencode(second_query)}",
        json={"data": {"html": second_page}},
    )
    config = SourceConfig(
        "miit",
        "工业和信息化部",
        "全国",
        (list_url,),
        ("www.miit.gov.cn",),
        request_interval_seconds=0,
    )
    source = MiitSource(config, OfficialHttpClient(config))

    candidates = source.discover(date(2026, 6, 1), date(2026, 7, 31))

    assert [candidate.title for candidate in candidates] == [
        "智能工厂建设通知",
        "工业和信息化部公告",
    ]
    assert [candidate.published_at for candidate in candidates] == [
        date(2026, 7, 28),
        date(2026, 6, 15),
    ]
