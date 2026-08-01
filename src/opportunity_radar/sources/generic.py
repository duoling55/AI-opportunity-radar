from __future__ import annotations

from opportunity_radar.sources.base import GenericHtmlSource

# 政府门户政策列表常见选择器，按优先级排列；末位 a 为兜底。
_DEFAULT_LISTING_SELECTORS: tuple[str, ...] = (
    "ul.list li a",
    ".policy-list a",
    ".list-content a",
    ".govlist a",
    "a",
)
# 政府公文详情正文常见容器
_DEFAULT_DETAIL_SELECTORS: tuple[str, ...] = (
    ".content",
    ".article",
    "#zoom",
    ".TRS_Editor",
    "article",
    "main",
)


class GenericGovSource(GenericHtmlSource):
    """按 sources.json 配置实例化的通用政府信源适配器，无需专用适配器文件。

    复用 GenericHtmlSource 的列表发现与日期解析逻辑，仅提供政府门户常见 CSS 选择器。
    由 registry.resolve_adapter 在 origin=discovery 或 adapter_version=generic 时选用。
    """

    listing_item_selectors = _DEFAULT_LISTING_SELECTORS
    detail_content_selectors = _DEFAULT_DETAIL_SELECTORS
