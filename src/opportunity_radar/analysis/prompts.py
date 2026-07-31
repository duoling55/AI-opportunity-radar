from __future__ import annotations

import json
from collections.abc import Mapping

from opportunity_radar.models import PolicyAnalysis

SYSTEM_PROMPT = """你是政策商机分析助手。只依据提供的政策正文，不得浏览、搜索或使用任何外部来源，不得编造文号、日期、补贴、企业事实或政策资格。每条行业机会必须给出不超过240字的原文短摘录和定位。禁止承诺补贴获得、融资审批或政府背书。只输出与给定 JSON Schema 匹配的 JSON。"""

USER_PROMPT_TEMPLATE = """政策正文：
{{document_text}}

允许行业代码与名称：{{industry_catalog}}
允许业务标签：{{business_tags}}
允许机会场景：设备采购、设备更新、技术改造、扩产、生产线建设、车辆更新、绿色转型、数字化转型。
行业层级约束：section_code 必须是一位大写字母门类代码；division_code 必须是同一门类开头的一位大写字母加两位数字的大类代码。

证据约束：每条 evidence.quote 必须是政策正文中的原文；summary 可概括政策内容，无需逐字复制政策正文。没有原文证据时不得输出该商机。

authoritative JSON Schema（服务端仅保证 JSON 对象；此 schema 将在本地严格校验）：
{{json_schema}}"""

USER_PROMPT_PLACEHOLDERS = (
    "{{document_text}}",
    "{{industry_catalog}}",
    "{{business_tags}}",
    "{{json_schema}}",
)


def validate_user_prompt_template(template: str) -> str:
    normalized = template.strip()
    if not normalized:
        raise ValueError("用户提示词模板不能为空")
    missing = [item for item in USER_PROMPT_PLACEHOLDERS if item not in normalized]
    if missing:
        raise ValueError("用户提示词模板缺少占位符：" + "、".join(missing))
    return normalized


def build_user_prompt(
    document_text: str,
    industry_catalog: Mapping[str, str] | set[str],
    business_tags: list[str],
    template: str = USER_PROMPT_TEMPLATE,
) -> str:
    schema = json.dumps(
        PolicyAnalysis.model_json_schema(),
        ensure_ascii=False,
        separators=(",", ":"),
    )
    allowed_industries = (
        dict(sorted(industry_catalog.items()))
        if isinstance(industry_catalog, Mapping)
        else sorted(industry_catalog)
    )
    resolved = validate_user_prompt_template(template)
    replacements = {
        "{{document_text}}": document_text,
        "{{industry_catalog}}": str(allowed_industries),
        "{{business_tags}}": str(business_tags),
        "{{json_schema}}": schema,
    }
    for placeholder, value in replacements.items():
        resolved = resolved.replace(placeholder, value)
    return resolved
