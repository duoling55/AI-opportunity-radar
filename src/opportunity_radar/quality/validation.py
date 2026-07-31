from __future__ import annotations

from opportunity_radar.models import IndustryOpportunity, PolicyDocument
from opportunity_radar.quality.scripts import is_compliant_script


def required_fields_review_reason(
    document: PolicyDocument, opportunity: IndustryOpportunity
) -> str | None:
    """Return a review reason when a priority row cannot be traced or acted on."""
    if document.attachment_errors:
        return f"附件解析不完整：{document.attachment_errors[0]}"

    traceability_fields = (
        ("政策名称", document.title),
        ("来源标识", document.source_id),
        ("来源名称", document.source_name),
        ("原文链接", str(document.detail_url)),
        ("原始正文", document.raw_text),
        ("规范正文", document.normalized_text),
    )
    for label, value in traceability_fields:
        if not value.strip():
            return f"政策追溯信息不完整：{label}"

    industry_fields = (
        opportunity.section_code,
        opportunity.section_name,
        opportunity.division_code,
        opportunity.division_name,
    )
    if not all(value.strip() for value in industry_fields):
        return "标准行业分类信息不完整"
    if not any(tag.strip() for tag in opportunity.business_tags):
        return "缺少有效业务行业标签"
    if not any(scenario.strip() for scenario in opportunity.scenarios):
        return "缺少明确的机会场景"
    return None


def opportunity_review_reason(opportunity: IndustryOpportunity) -> str | None:
    """Return the reason an opportunity must be reviewed instead of prioritized."""
    if not opportunity.evidence:
        return "缺少可定位的行业原文依据"
    if not is_compliant_script(opportunity.opening_script):
        return "营销话术含过度承诺或政府背书表达"
    return None
