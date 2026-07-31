from opportunity_radar.sources.base import GenericHtmlSource


class ZhejiangHuiqiSource(GenericHtmlSource):
    listing_item_selectors = (".policy-list .policy-item",)
    detail_content_selectors = ("#policy-detail", ".policy-detail", "article", "main")
