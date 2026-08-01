from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from opportunity_radar.config import SourceConfig
from opportunity_radar.http import OfficialHttpClient
from opportunity_radar.models import PolicyCandidate
from opportunity_radar.parsing.html import DocumentRetriever
from opportunity_radar.sources.zhejiang_huiqi import ZhejiangHuiqiSource

LIST_API = "https://zj87.jxt.zj.gov.cn/webapi/extMsPolicyInfo/list"
DETAIL_API = "https://zj87.jxt.zj.gov.cn/webapi/PolicyInfo/pcConsultDetail"
DETAIL_URL = "https://zj87.jxt.zj.gov.cn/zjhqpt/views/policy-zw/detail.html?id=101"


def _source() -> ZhejiangHuiqiSource:
    config = SourceConfig(
        "zhejiang_huiqi",
        "浙江省惠企政策信息平台",
        "浙江",
        ("https://zj87.jxt.zj.gov.cn/zjhqpt/views/policy-zw/list.html",),
        ("zj87.jxt.zj.gov.cn",),
        request_interval_seconds=0,
    )
    return ZhejiangHuiqiSource(config, OfficialHttpClient(config))


def test_zhejiang_huiqi_discovers_api_entries_in_requested_date_range(httpx_mock) -> None:
    source = _source()
    httpx_mock.add_response(
        url=LIST_API,
        method="POST",
        json={
            "status": 1,
            "body": {
                "totalPage": 1,
                "list": [
                    {"id": 101, "title": "设备更新支持通知", "publishDate": "2026-07-20"},
                    {"id": 102, "title": "历史政策通知", "publishDate": "2026-06-30"},
                ],
            },
        },
    )

    candidates = source.discover(date(2026, 7, 1), date(2026, 7, 31))

    assert [(item.title, str(item.detail_url), item.published_at) for item in candidates] == [
        ("设备更新支持通知", DETAIL_URL, date(2026, 7, 20))
    ]


def test_zhejiang_huiqi_pages_until_the_remaining_results_precede_start_date(httpx_mock) -> None:
    source = _source()
    httpx_mock.add_response(
        url=LIST_API,
        method="POST",
        json={
            "status": 1,
            "body": {
                "totalPage": 3,
                "list": [
                    {"id": 101, "title": "第一页政策", "publishDate": "2026-07-20"},
                    {"id": 102, "title": "第一页另一政策", "publishDate": "2026-07-15"},
                ],
            },
        },
    )
    httpx_mock.add_response(
        url=LIST_API,
        method="POST",
        json={
            "status": 1,
            "body": {
                "totalPage": 3,
                "list": [
                    {"id": 101, "title": "重复政策", "publishDate": "2026-07-20"},
                    {"id": 103, "title": "第二页政策", "publishDate": "2026-07-10"},
                ],
            },
        },
    )
    httpx_mock.add_response(
        url=LIST_API,
        method="POST",
        json={
            "status": 1,
            "body": {
                "totalPage": 3,
                "list": [{"id": 104, "title": "过期政策", "publishDate": "2026-06-30"}],
            },
        },
    )

    candidates = source.discover(date(2026, 7, 1), date(2026, 7, 31))

    assert [item.detail_url.query for item in candidates] == ["id=101", "id=102", "id=103"]
    assert [request.content for request in httpx_mock.get_requests()] == [
        b"keywords=&policyCategory=&applyAreaId=&departmentId=&isDeclare=&orderby=2&pageNum=1&pageSize=100&declareClick=",
        b"keywords=&policyCategory=&applyAreaId=&departmentId=&isDeclare=&orderby=2&pageNum=2&pageSize=100&declareClick=",
        b"keywords=&policyCategory=&applyAreaId=&departmentId=&isDeclare=&orderby=2&pageNum=3&pageSize=100&declareClick=",
    ]


def test_document_retriever_delegates_zhejiang_huiqi_detail_api_and_saves_json_snapshot(
    httpx_mock, tmp_path: Path
) -> None:
    source = _source()
    httpx_mock.add_response(
        url=DETAIL_API,
        method="POST",
        json={
            "status": 1,
            "body": {
                "id": 101,
                "title": "设备更新支持通知",
                "code": "浙经信〔2026〕1号",
                "department": "浙江省经济和信息化厅",
                "publishdate": "2026-07-20",
                "content_trim": "支持企业采购节能设备。",
                "content": "摘要",
                "intercontent": "解读",
            },
        },
    )
    candidate = PolicyCandidate(
        source_id="zhejiang_huiqi",
        title="设备更新支持通知",
        detail_url=DETAIL_URL,
        published_at=date(2026, 7, 20),
    )

    document = DocumentRetriever().fetch_document(
        source,
        candidate,
        datetime(2026, 7, 21, tzinfo=UTC),
        tmp_path,
    )

    assert document.raw_text == "支持企业采购节能设备。"
    assert document.document_number == "浙经信〔2026〕1号"
    assert Path(document.snapshot_path).suffix == ".json"
    assert Path(document.snapshot_path).read_text(encoding="utf-8").startswith("{")


def test_zhejiang_huiqi_fails_closed_when_detail_api_is_unsuccessful(httpx_mock, tmp_path: Path) -> None:
    source = _source()
    httpx_mock.add_response(url=DETAIL_API, method="POST", json={"status": 0, "body": {}})
    candidate = PolicyCandidate(
        source_id="zhejiang_huiqi",
        title="设备更新支持通知",
        detail_url=DETAIL_URL,
        published_at=date(2026, 7, 20),
    )

    with pytest.raises(RuntimeError, match="detail API returned an unsuccessful status"):
        DocumentRetriever().fetch_document(
            source,
            candidate,
            datetime(2026, 7, 21, tzinfo=UTC),
            tmp_path,
        )
