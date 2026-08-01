from datetime import date
from pathlib import Path

import pytest

from opportunity_radar.config import SourceConfig
from opportunity_radar.http import OfficialHttpClient
from opportunity_radar.sources.base import GenericHtmlSource


def test_client_ignores_environment_proxy_settings(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class FakeClient:
        def __init__(self, **kwargs: object) -> None:
            captured.update(kwargs)

    monkeypatch.setattr("opportunity_radar.http.httpx.Client", FakeClient)

    OfficialHttpClient(SourceConfig("demo", "演示", "全国", (), ("policy.example.gov.cn",)))

    assert captured["trust_env"] is False


def test_discovery_extracts_detail_link_and_date(httpx_mock) -> None:
    config = SourceConfig(
        "demo",
        "演示",
        "全国",
        ("https://policy.example.gov.cn/list",),
        ("policy.example.gov.cn",),
        request_interval_seconds=0,
    )
    httpx_mock.add_response(
        url="https://policy.example.gov.cn/list",
        text=(
            '<div><a href="/art/1.html">设备更新通知</a><span>2026-07-20</span></div>'
            '<div><a href="/art/2.html">产业扶持政策</a><span>2026-06-30</span></div>'
        ),
    )

    result = GenericHtmlSource(config, OfficialHttpClient(config)).discover(
        date(2026, 7, 1), date(2026, 7, 30)
    )

    assert str(result[0].detail_url) == "https://policy.example.gov.cn/art/1.html"
    assert result[0].published_at == date(2026, 7, 20)
    assert len(result) == 1


def test_client_rejects_non_official_domain() -> None:
    config = SourceConfig("demo", "演示", "全国", (), ("policy.example.gov.cn",))

    with pytest.raises(ValueError, match="allow-listed"):
        OfficialHttpClient(config).get("https://not-official.example/list")


def test_client_posts_form_data_to_an_allowlisted_source(httpx_mock) -> None:
    config = SourceConfig(
        "demo",
        "演示",
        "全国",
        (),
        ("policy.example.gov.cn",),
        request_interval_seconds=0,
    )
    httpx_mock.add_response(
        url="https://policy.example.gov.cn/list",
        method="POST",
        json={"status": 1},
    )

    response = OfficialHttpClient(config).post(
        "https://policy.example.gov.cn/list",
        {"pageNum": 1, "pageSize": 100},
    )

    assert response.json() == {"status": 1}
    request = httpx_mock.get_requests()[0]
    assert request.method == "POST"
    assert request.content == b"pageNum=1&pageSize=100"


def test_client_rejects_post_to_non_official_domain() -> None:
    config = SourceConfig("demo", "演示", "全国", (), ("policy.example.gov.cn",))

    with pytest.raises(ValueError, match="allow-listed"):
        OfficialHttpClient(config).post("https://attacker.example/list", {"pageNum": 1})


def test_client_rejects_redirect_to_non_official_domain(httpx_mock) -> None:
    config = SourceConfig(
        "demo",
        "演示",
        "全国",
        (),
        ("policy.example.gov.cn",),
        request_interval_seconds=0,
    )
    httpx_mock.add_response(
        url="https://policy.example.gov.cn/list",
        status_code=302,
        headers={"Location": "https://not-official.example/landing"},
    )

    with pytest.raises(ValueError, match="allow-listed"):
        OfficialHttpClient(config).get("https://policy.example.gov.cn/list")

    assert [str(request.url) for request in httpx_mock.get_requests()] == [
        "https://policy.example.gov.cn/list"
    ]


def test_discovery_discards_off_domain_links(httpx_mock) -> None:
    config = SourceConfig(
        "demo",
        "演示",
        "全国",
        ("https://policy.example.gov.cn/list",),
        ("policy.example.gov.cn",),
        request_interval_seconds=0,
    )
    listing = Path("tests/fixtures/listing.html").read_text(encoding="utf-8")
    httpx_mock.add_response(url="https://policy.example.gov.cn/list", text=listing)

    result = GenericHtmlSource(config, OfficialHttpClient(config)).discover(
        date(2026, 7, 1), date(2026, 7, 30)
    )

    assert [str(candidate.detail_url) for candidate in result] == [
        "https://policy.example.gov.cn/art/1.html"
    ]


def test_discovery_uses_each_links_local_date_in_a_shared_container(httpx_mock) -> None:
    config = SourceConfig(
        "demo",
        "演示",
        "全国",
        ("https://policy.example.gov.cn/list",),
        ("policy.example.gov.cn",),
        request_interval_seconds=0,
    )
    httpx_mock.add_response(
        url="https://policy.example.gov.cn/list",
        text=(
            '<div><a href="/art/old.html">设备更新通知</a><span>2026-06-30</span>'
            '<a href="/art/current.html">产业扶持政策</a><span>2026-07-20</span></div>'
        ),
    )

    result = GenericHtmlSource(config, OfficialHttpClient(config)).discover(
        date(2026, 7, 1), date(2026, 7, 30)
    )

    assert [str(candidate.detail_url) for candidate in result] == [
        "https://policy.example.gov.cn/art/current.html"
    ]
    assert result[0].published_at == date(2026, 7, 20)


@pytest.mark.parametrize("status_code", [401, 403, 429])
def test_client_stops_on_restricted_status(httpx_mock, status_code: int) -> None:
    config = SourceConfig(
        "demo",
        "演示",
        "全国",
        (),
        ("policy.example.gov.cn",),
        request_interval_seconds=0,
    )
    url = "https://policy.example.gov.cn/list"
    httpx_mock.add_response(url=url, status_code=status_code)

    with pytest.raises(PermissionError, match=f"restricted: {status_code}"):
        OfficialHttpClient(config).get(url)

    assert len(httpx_mock.get_requests()) == 1


def test_client_waits_configured_interval_before_request(httpx_mock, monkeypatch) -> None:
    config = SourceConfig(
        "demo",
        "演示",
        "全国",
        (),
        ("policy.example.gov.cn",),
        request_interval_seconds=1.75,
    )
    url = "https://policy.example.gov.cn/list"
    waits: list[float] = []
    monkeypatch.setattr("opportunity_radar.http.time.sleep", waits.append)
    httpx_mock.add_response(url=url)

    OfficialHttpClient(config).get(url)

    assert waits == [1.75]


def test_client_paces_each_allowlisted_redirect_hop(httpx_mock, monkeypatch) -> None:
    config = SourceConfig(
        "demo",
        "演示",
        "全国",
        (),
        ("policy.example.gov.cn",),
        request_interval_seconds=1.25,
    )
    waits: list[float] = []
    monkeypatch.setattr("opportunity_radar.http.time.sleep", waits.append)
    httpx_mock.add_response(
        url="https://policy.example.gov.cn/start",
        status_code=302,
        headers={"Location": "/final"},
    )
    httpx_mock.add_response(url="https://policy.example.gov.cn/final")

    OfficialHttpClient(config).get("https://policy.example.gov.cn/start")

    assert waits == [1.25, 1.25]
