from opportunity_radar.sources.base import GenericHtmlSource


class JiangsuGovernmentSource(GenericHtmlSource):
    listing_item_selectors = (".art_list li",)
    detail_content_selectors = (".article-content", "article", "main")
