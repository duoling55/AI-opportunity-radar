from opportunity_radar.sources.base import GenericHtmlSource


class NdrcSource(GenericHtmlSource):
    listing_item_selectors = (".list li",)
    detail_content_selectors = (".article_con", "article", "main")
