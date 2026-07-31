from datetime import UTC, date, datetime

import pytest
from pydantic import ValidationError

from opportunity_radar.models import (
    Evidence,
    IndustryOpportunity,
    PolicyAnalysis,
    PolicyCandidate,
    PolicyDocument,
)


def test_industry_opportunity_rejects_unknown_confidence() -> None:
    with pytest.raises(ValidationError):
        IndustryOpportunity(
            section_code="C",
            section_name="制造业",
            division_code="C34",
            division_name="通用设备制造业",
            business_tags=["通用装备制造"],
            confidence=1.2,
            scenarios=["设备更新"],
            evidence=[Evidence(quote="设备更新", location="第2段")],
            leasing_relevance="设备可通过融资租赁配置",
            recommended_action="联系园区客户经理",
            opening_script="近期设备更新政策可支持贵司设备升级。",
        )


def test_policy_candidate_accepts_http_url_and_optional_date() -> None:
    candidate = PolicyCandidate(
        source_id="zj",
        title="政策通知",
        detail_url="https://example.gov.cn/policy/1",
        published_at=date(2026, 7, 1),
    )

    assert str(candidate.detail_url) == "https://example.gov.cn/policy/1"
    assert candidate.published_at == date(2026, 7, 1)


def test_policy_document_requires_raw_and_normalized_text() -> None:
    with pytest.raises(ValidationError):
        PolicyDocument(
            policy_id="p-1",
            source_id="zj",
            source_name="浙江",
            region="浙江",
            title="政策通知",
            detail_url="https://example.gov.cn/policy/1",
            collected_at=datetime(2026, 7, 1, tzinfo=UTC),
            content_hash="abc",
            snapshot_path="data/raw/p-1.html",
        )


def test_non_benefit_policy_rejects_opportunities() -> None:
    opportunity = IndustryOpportunity(
        section_code="C",
        section_name="制造业",
        division_code="C34",
        division_name="通用设备制造业",
        business_tags=["通用装备制造"],
        confidence=0.8,
        scenarios=["设备更新"],
        evidence=[Evidence(quote="设备更新", location="第2段")],
        leasing_relevance="设备可通过融资租赁配置",
        recommended_action="联系园区客户经理",
        opening_script="近期设备更新政策可支持贵司设备升级。",
    )

    with pytest.raises(ValidationError, match="non-benefit policy"):
        PolicyAnalysis(
            is_benefit_policy=False,
            summary="监管要求",
            support_direction="无",
            opportunities=[opportunity],
        )
