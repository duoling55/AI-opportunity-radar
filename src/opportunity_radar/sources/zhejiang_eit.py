from opportunity_radar.sources.base import GenericHtmlSource


class ZhejiangEitSource(GenericHtmlSource):
    listing_item_selectors = (".default_pgContainer li",)
    detail_content_selectors = (".article-content", "article", "main")
