from dataclasses import replace
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from opportunity_radar.config import SourceConfig, load_sources
from opportunity_radar.http import OfficialHttpClient
from opportunity_radar.parsing.html import DocumentRetriever
from opportunity_radar.sources.jiangsu_eit import JiangsuEitSource
from opportunity_radar.sources.jiangsu_government import JiangsuGovernmentSource
from opportunity_radar.sources.miit import MiitSource
from opportunity_radar.sources.ndrc import NdrcSource
from opportunity_radar.sources.registry import build_sources
from opportunity_radar.sources.zhejiang_eit import ZhejiangEitSource
from opportunity_radar.sources.zhejiang_huiqi import ZhejiangHuiqiSource


def test_registry_builds_one_adapter_and_client_per_configured_source() -> None:
    configs = load_sources(Path("config/sources.json"))

    sources = build_sources(configs)

    assert {source_id: type(source) for source_id, source in sources.items()} == {
        "miit": MiitSource,
        "ndrc": NdrcSource,
        "zhejiang_huiqi": ZhejiangHuiqiSource,
        "zhejiang_eit": ZhejiangEitSource,
        "jiangsu_government": JiangsuGovernmentSource,
        "jiangsu_eit": JiangsuEitSource,
    }
    clients = [source.client for source in sources.values()]
    assert len({id(client) for client in clients}) == len(clients)


def test_registry_omits_disabled_sources() -> None:
    configs = {
        "miit": SourceConfig(
            "miit",
            "工业和信息化部",
            "全国",
            ("https://www.miit.gov.cn/gyhxxhbwjcx/",),
            ("www.miit.gov.cn",),
            enabled=False,
        )
    }

    assert build_sources(configs) == {}


@pytest.mark.parametrize(
    ("source_id", "source_type", "expected_path"),
    [
        ("miit", MiitSource, "/policy/miit.html"),
        ("ndrc", NdrcSource, "/policy/ndrc.html"),
        ("zhejiang_huiqi", ZhejiangHuiqiSource, "/policy/zhejiang-huiqi.html"),
        ("zhejiang_eit", ZhejiangEitSource, "/policy/zhejiang-eit.html"),
        ("jiangsu_government", JiangsuGovernmentSource, "/policy/jiangsu-government.html"),
        ("jiangsu_eit", JiangsuEitSource, "/policy/jiangsu-eit.html"),
    ],
)
def test_each_source_uses_its_fixture_specific_listing_and_detail_selectors(
    httpx_mock,
    tmp_path: Path,
    source_id: str,
    source_type: type,
    expected_path: str,
) -> None:
    config = replace(
        load_sources(Path("config/sources.json"))[source_id],
        request_interval_seconds=0,
    )
    list_url = config.list_urls[0]
    detail_url = f"https://{config.allowed_domains[0]}{expected_path}"
    listing = Path(f"tests/fixtures/sources/{source_id}_listing.html").read_text(
        encoding="utf-8"
    )
    detail = Path(f"tests/fixtures/sources/{source_id}_detail.html").read_text(
        encoding="utf-8"
    )
    httpx_mock.add_response(url=list_url, text=listing)
    httpx_mock.add_response(url=detail_url, text=detail)
    source = source_type(config, OfficialHttpClient(config))

    candidates = source.discover(date(2026, 7, 1), date(2026, 7, 31))
    document = DocumentRetriever().fetch_document(
        source,
        candidates[0],
        datetime(2026, 7, 29, tzinfo=UTC),
        tmp_path,
    )

    assert len(candidates) == 1
    assert str(candidates[0].detail_url) == detail_url
    assert document.raw_text == f"{source_id} 支持设备更新。"
    assert "导航通知" not in document.raw_text
