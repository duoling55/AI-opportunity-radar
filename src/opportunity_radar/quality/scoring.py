from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime

from opportunity_radar.models import IndustryOpportunity, PolicyDocument
from opportunity_radar.normalization import normalize_text
from opportunity_radar.quality.validation import (
    opportunity_review_reason,
    required_fields_review_reason,
)


@dataclass(frozen=True)
class QualityResult:
    score: int
    grade: str
    sheet_name: str
    review_reason: str | None = None


def evaluate_score(
    *,
    source_complete: bool,
    evidence_complete: bool,
    timely: bool,
    industry_clear: bool,
    support_strength: int,
    leasing_strength: int,
    actionable: bool,
) -> QualityResult:
    """Score a complete policy opportunity, without allowing a total over 100."""
    if not evidence_complete:
        return QualityResult(0, "观察", "政策观察", "缺少可定位的行业原文依据")

    support_score = max(0, min(support_strength, 15))
    leasing_score = max(0, min(leasing_strength, 30))
    score = (
        (15 if source_complete else 0)
        + (10 if timely else 0)
        + (20 if industry_clear else 0)
        + support_score
        + leasing_score
        + (10 if actionable else 0)
    )
    if not timely:
        score = min(score, 59)
    grade = "A" if score >= 80 else "B" if score >= 60 else "C" if score >= 40 else "观察"

    complete_for_priority = source_complete and industry_clear and leasing_score > 0
    if not timely:
        return QualityResult(score, grade, "政策观察", "政策申报已截止")
    if grade in {"A", "B"} and complete_for_priority:
        return QualityResult(score, grade, "重点商机")
    if not source_complete:
        return QualityResult(score, grade, "政策观察", "来源信息不完整")
    if not industry_clear:
        return QualityResult(score, grade, "政策观察", "行业判断不明确")
    if leasing_score == 0:
        return QualityResult(score, grade, "政策观察", "缺少明确的机会场景")
    return QualityResult(score, grade, "政策观察")


def support_strength(text: str) -> int:
    if any(term in text for term in ("补贴", "奖励", "贴息", "专项资金")):
        return 15
    if any(term in text for term in ("支持", "试点", "培育")):
        return 8
    return 3


def leasing_strength(scenarios: list[str]) -> int:
    joined = " ".join(scenarios)
    if any(term in joined for term in ("设备采购", "设备更新", "技术改造", "扩产", "生产线", "车辆")):
        return 30
    if any(term in joined for term in ("数字化", "节能", "绿色")):
        return 15
    return 5 if joined.strip() else 0


def evaluate(
    document: PolicyDocument,
    opportunity: IndustryOpportunity,
    *,
    reference_date: date | None = None,
) -> QualityResult:
    """Apply compliance gates, then score and route one policy-industry opportunity."""
    if review_reason := required_fields_review_reason(document, opportunity):
        return QualityResult(0, "观察", "政策观察", review_reason)
    if review_reason := opportunity_review_reason(opportunity):
        return QualityResult(0, "观察", "政策观察", review_reason)
    if not _has_verifiable_evidence(document, opportunity):
        return QualityResult(0, "观察", "政策观察", "缺少可定位的行业原文依据")

    effective_reference_date = reference_date or datetime.now(UTC).date()
    if review_reason := _timing_review_reason(document):
        return QualityResult(0, "观察", "政策观察", review_reason)
    return evaluate_score(
        source_complete=True,
        evidence_complete=bool(opportunity.evidence),
        timely=(
            document.application_end_date is None
            or document.application_end_date >= effective_reference_date
        ),
        industry_clear=opportunity.confidence >= 0.7,
        support_strength=support_strength(document.normalized_text),
        leasing_strength=leasing_strength(opportunity.scenarios),
        actionable=bool(opportunity.recommended_action.strip()),
    )


def _timing_review_reason(document: PolicyDocument) -> str | None:
    timing = (
        document.publish_date,
        document.effective_date,
        document.application_start_date,
        document.application_end_date,
    )
    if not any(timing):
        return "政策时效信息不明确"
    if (
        document.application_start_date
        and document.application_end_date
        and document.application_end_date < document.application_start_date
    ):
        return "政策日期存在矛盾"
    if (
        document.publish_date
        and document.application_end_date
        and document.application_end_date < document.publish_date
    ):
        return "政策日期存在矛盾"
    return None


def _has_verifiable_evidence(document: PolicyDocument, opportunity: IndustryOpportunity) -> bool:
    policy_text = normalize_text(document.normalized_text)
    return bool(policy_text) and all(
        (expected_location := _canonical_evidence_location(policy_text, evidence.quote))
        and evidence.location == expected_location
        for evidence in opportunity.evidence
    )


def _canonical_evidence_location(policy_text: str, quote: str) -> str | None:
    """Return a one-based inclusive range in the ``normalize_text`` coordinate system."""
    normalized_quote = normalize_text(quote)
    start = policy_text.find(normalized_quote) if normalized_quote else -1
    if start < 0:
        return None
    return f"正文字符{start + 1}-{start + len(normalized_quote)}"
