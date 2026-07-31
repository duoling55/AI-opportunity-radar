from opportunity_radar.sources.base import GenericHtmlSource


class MiitSource(GenericHtmlSource):
    listing_item_selectors = (".clist li",)
    detail_content_selectors = (".article", "article", "main")
