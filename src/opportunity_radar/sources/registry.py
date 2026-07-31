from __future__ import annotations

from opportunity_radar.config import SourceConfig
from opportunity_radar.http import OfficialHttpClient
from opportunity_radar.sources.base import GenericHtmlSource, PolicySource
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


def build_sources(configs: dict[str, SourceConfig]) -> dict[str, PolicySource]:
    return {
        source_id: SOURCE_TYPES[source_id](config, OfficialHttpClient(config))
        for source_id, config in configs.items()
        if config.enabled
    }
