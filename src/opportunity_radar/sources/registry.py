from __future__ import annotations

from opportunity_radar.config import SourceConfig
from opportunity_radar.http import OfficialHttpClient
from opportunity_radar.sources.base import GenericHtmlSource, PolicySource
from opportunity_radar.sources.generic import GenericGovSource
from opportunity_radar.sources.jiangsu_eit import JiangsuEitSource
from opportunity_radar.sources.jiangsu_government import JiangsuGovernmentSource
from opportunity_radar.sources.miit import MiitSource
from opportunity_radar.sources.ndrc import NdrcSource
from opportunity_radar.sources.zhejiang_eit import ZhejiangEitSource
from opportunity_radar.sources.zhejiang_huiqi import ZhejiangHuiqiSource

SOURCE_TYPES: dict[str, type[GenericHtmlSource]] = {
    "miit": MiitSource,
    "ndrc": NdrcSource,
    "zhejiang_huiqi": ZhejiangHuiqiSource,
    "zhejiang_eit": ZhejiangEitSource,
    "jiangsu_government": JiangsuGovernmentSource,
    "jiangsu_eit": JiangsuEitSource,
}


def resolve_adapter(config: SourceConfig) -> type[GenericHtmlSource]:
    """专用适配器优先；origin=discovery 或 adapter_version=generic 走 GenericGovSource。"""
    dedicated = SOURCE_TYPES.get(config.source_id)
    if dedicated is not None:
        return dedicated
    if config.origin == "discovery" or config.adapter_version == "generic":
        return GenericGovSource
    raise KeyError(f"无适配器: {config.source_id}")


def build_sources(configs: dict[str, SourceConfig]) -> dict[str, PolicySource]:
    return {
        source_id: resolve_adapter(config)(config, OfficialHttpClient(config))
        for source_id, config in configs.items()
        if config.enabled
    }
