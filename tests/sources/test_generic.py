from datetime import date

from opportunity_radar.config import SourceConfig
from opportunity_radar.sources.generic import GenericGovSource
from opportunity_radar.sources.registry import resolve_adapter


def _config() -> SourceConfig:
    return SourceConfig(
        source_id="gov_disc",
        display_name="发现信源",
        region="国家",
        list_urls=("https://www.gov.cn/zc/index.html",),
        allowed_domains=("www.gov.cn",),
        origin="discovery",
        adapter_version="generic",
    )


def test_generic_source_discovers_from_html() -> None:
    html = '<ul class="list"><li><a href="/p/1">关于设备更新的通知</a></li></ul>'
    src = GenericGovSource(_config(), client=None)
    candidates = src.discover_from_html(
        "https://www.gov.cn/zc/index.html",
        html,
        date(2026, 1, 1),
        date(2026, 12, 31),
    )
    assert any("设备更新" in c.title for c in candidates)
    assert str(candidates[0].detail_url) == "https://www.gov.cn/p/1"


def test_registry_routes_discovery_to_generic() -> None:
    assert resolve_adapter(_config()) is GenericGovSource


def test_registry_prefers_dedicated_adapter() -> None:
    miit = SourceConfig(
        source_id="miit",
        display_name="工信部",
        region="全国",
        list_urls=("https://www.miit.gov.cn/xwfb/zxzc/index.html",),
        allowed_domains=("www.miit.gov.cn",),
        adapter_version="1.0.2",
    )
    from opportunity_radar.sources.miit import MiitSource

    assert resolve_adapter(miit) is MiitSource
