from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from opportunity_radar.models import (
    Evidence,
    IndustryOpportunity,
    PolicyAnalysis,
    PolicyCandidate,
    PolicyDocument,
)


class FixtureSource:
    """A local, deterministic policy source for end-to-end pipeline tests."""

    def __init__(self, *, two_policy_documents_with_distinct_evidence: bool) -> None:
        if not two_policy_documents_with_distinct_evidence:
            raise ValueError("the fixture source requires two distinct policy documents")

    def discover(self, start: date, end: date) -> list[PolicyCandidate]:
        return [
            PolicyCandidate(
                source_id="fixture",
                title="priority-policy",
                detail_url="https://fixture.example/priority-policy",
                published_at=date(2026, 7, 10),
            ),
            PolicyCandidate(
                source_id="fixture",
                title="observation-policy",
                detail_url="https://fixture.example/observation-policy",
                published_at=date(2026, 7, 11),
            ),
        ]


class FixtureRetriever:
    def __init__(self, documents: dict[str, PolicyDocument]) -> None:
        self._documents = documents

    def fetch_document(
        self,
        source: FixtureSource,
        candidate: PolicyCandidate,
        collected_at: datetime,
        raw_dir: Path,
    ) -> PolicyDocument:
        del source, collected_at, raw_dir
        return self._documents[candidate.title]


class MappingAnalyzer:
    def __init__(self, analyses: dict[str, PolicyAnalysis]) -> None:
        self._analyses = analyses

    def analyze(
        self,
        document: PolicyDocument,
        valid_codes: set[str],
        business_tags: list[str],
    ) -> PolicyAnalysis:
        del valid_codes, business_tags
        return self._analyses[document.title]


def _document(title: str, raw_text: str) -> PolicyDocument:
    return PolicyDocument(
        policy_id=title,
        source_id="fixture",
        source_name="本地测试政策源",
        region="全国",
        title=title,
        detail_url=f"https://fixture.example/{title}",
        publisher="本地测试发布机构",
        publish_date=date(2026, 7, 10),
        raw_text=raw_text,
        normalized_text=raw_text,
        collected_at=datetime(2026, 7, 29, tzinfo=UTC),
        content_hash=f"fixture-{title}",
        snapshot_path=f"raw/{title}.html",
    )


def _opportunity(evidence: Evidence, *, confidence: float) -> IndustryOpportunity:
    return IndustryOpportunity(
        section_code="C",
        section_name="制造业",
        division_code="C34",
        division_name="通用设备制造业",
        business_tags=["通用装备制造"],
        confidence=confidence,
        scenarios=["设备更新"],
        evidence=[evidence],
        leasing_relevance="设备可通过融资租赁配置",
        recommended_action="联系园区客户经理",
        opening_script="我们可以交流近期设备更新安排",
    )


@pytest.fixture
def fixture_sources() -> dict[str, FixtureSource]:
    return {"fixture": FixtureSource(two_policy_documents_with_distinct_evidence=True)}


@pytest.fixture
def fixture_retriever() -> FixtureRetriever:
    return FixtureRetriever(
        {
            "priority-policy": _document(
                "priority-policy",
                "支持通用设备制造企业开展设备更新，给予补贴。",
            ),
            "observation-policy": _document(
                "observation-policy",
                "鼓励通用设备制造企业推进技术改造。",
            ),
        }
    )


@pytest.fixture
def fixture_analyzer() -> MappingAnalyzer:
    priority_analysis = PolicyAnalysis(
        is_benefit_policy=True,
        summary="设备更新补贴政策",
        support_direction="支持设备更新",
        opportunities=[
            _opportunity(Evidence(quote="设备更新", location="正文字符13-16"), confidence=0.9)
        ],
    )
    observation_analysis = PolicyAnalysis(
        is_benefit_policy=True,
        summary="技术改造观察政策",
        support_direction="鼓励技术改造",
        opportunities=[
            _opportunity(Evidence(quote="技术改造", location="正文字符13-16"), confidence=0.5)
        ],
    )
    return MappingAnalyzer(
        {
            "priority-policy": priority_analysis,
            "observation-policy": observation_analysis,
        }
    )
