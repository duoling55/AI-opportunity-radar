from opportunity_radar.sources.base import GenericHtmlSource


class JiangsuEitSource(GenericHtmlSource):
    listing_item_selectors = (".list-box li",)
    detail_content_selectors = (".TRS_Editor", "article", "main")
