from __future__ import annotations

import re

DISCLAIMER = "政策解读仅供业务参考，以政策原文及主管部门解释为准；融资方案及审批结果以正式评估为准。"

_GUARANTEE_PATTERN = re.compile(
    r"(?:保证|承诺|包过|肯定|一定|必然|必将).{0,12}"
    r"(?:补贴|补助|奖励|资金|审批|获批|通过|融资|贷款)"
    r"|(?:补贴|补助|奖励|资金|审批|获批|通过|融资|贷款).{0,12}"
    r"(?:保证|承诺|包过|肯定|一定|必然|必将)",
    re.DOTALL,
)
_GOVERNMENT_FINANCING_BACKSTOP = re.compile(
    r"(?:政府|官方).{0,16}(?:融资|贷款|方案).{0,16}(?:兜底|担保|保证|背书|增信)"
    r"|(?:融资|贷款|方案).{0,16}(?:政府|官方).{0,16}(?:兜底|担保|保证|背书|增信)"
    r"|(?:政府|官方).{0,16}(?:兜底|担保|保证|背书|增信).{0,16}(?:融资|贷款|方案)",
    re.DOTALL,
)
_GOVERNMENT_ENDORSEMENT = (
    "政府背书",
    "政府担保",
    "政府保证",
    "政府推荐",
    "政府认可",
    "官方背书",
)


def is_compliant_script(script: str) -> bool:
    """Return whether an opening script avoids guarantees and government endorsement."""
    candidate = script.strip()
    return bool(candidate) and not (
        _GUARANTEE_PATTERN.search(candidate)
        or _GOVERNMENT_FINANCING_BACKSTOP.search(candidate)
        or any(phrase in candidate for phrase in _GOVERNMENT_ENDORSEMENT)
    )


def append_disclaimer(script: str) -> str:
    """Add the required business-use disclaimer to a compliant opening script."""
    return f"{script.strip()}\n\n{DISCLAIMER}"
