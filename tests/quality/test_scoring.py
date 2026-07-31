from datetime import UTC, date, datetime

import pytest

from opportunity_radar.models import Evidence, IndustryOpportunity, PolicyDocument
from opportunity_radar.quality.scoring import evaluate, evaluate_score


def _document(**changes: object) -> PolicyDocument:
    values: dict[str, object] = {
        "policy_id": "policy-1",
        "source_id": "miit",
        "source_name": "工业和信息化部",
        "region": "全国",
        "title": "设备更新通知",
        "detail_url": "https://www.miit.gov.cn/policy/1",
        "publisher": "工业和信息化部",
        "publish_date": date(2026, 7, 20),
        "raw_text": "支持设备更新和技术改造。",
        "normalized_text": "支持设备更新和技术改造。",
        "collected_at": datetime(2026, 7, 29, tzinfo=UTC),
        "content_hash": "hash",
        "snapshot_path": "data/raw/policy-1.html",
    }
    values.update(changes)
    return PolicyDocument(**values)


def _opportunity(**changes: object) -> IndustryOpportunity:
    values: dict[str, object] = {
        "section_code": "C",
        "section_name": "制造业",
        "division_code": "C34",
        "division_name": "通用设备制造业",
        "business_tags": ["通用装备制造"],
        "confidence": 0.8,
        "scenarios": ["设备更新"],
        "evidence": [Evidence(quote="支持设备更新", location="正文字符1-6")],
        "leasing_relevance": "设备可通过融资租赁配置",
        "recommended_action": "联系园区客户经理",
        "opening_script": "我们可以交流近期设备更新安排",
    }
    values.update(changes)
    return IndustryOpportunity(**values)


def test_missing_evidence_always_routes_to_observation() -> None:
    result = evaluate_score(
        source_complete=True,
        evidence_complete=False,
        timely=True,
        industry_clear=True,
        support_strength=15,
        leasing_strength=30,
        actionable=True,
    )

    assert result.sheet_name == "政策观察"
    assert result.review_reason == "缺少可定位的行业原文依据"


@pytest.mark.parametrize(
    ("timely", "support", "leasing", "actionable", "expected_score", "grade"),
    [
        (True, 15, 10, True, 80, "A"),
        (False, 15, 0, True, 59, "C"),
        (False, 5, 0, False, 40, "C"),
        (False, 4, 0, False, 39, "观察"),
    ],
)
def test_grade_thresholds_and_total_score_cap(
    timely: bool,
    support: int,
    leasing: int,
    actionable: bool,
    expected_score: int,
    grade: str,
) -> None:
    result = evaluate_score(
        source_complete=True,
        evidence_complete=True,
        timely=timely,
        industry_clear=True,
        support_strength=support,
        leasing_strength=leasing,
        actionable=actionable,
    )

    assert result.score == expected_score
    assert result.score <= 100
    assert result.grade == grade


def test_ab_score_with_incomplete_source_cannot_enter_priority_sheet() -> None:
    result = evaluate_score(
        source_complete=False,
        evidence_complete=True,
        timely=True,
        industry_clear=True,
        support_strength=15,
        leasing_strength=30,
        actionable=True,
    )

    assert result.grade == "A"
    assert result.sheet_name == "政策观察"
    assert result.review_reason == "来源信息不完整"


def test_expired_policy_with_maximum_other_scores_cannot_enter_priority_sheet() -> None:
    result = evaluate_score(
        source_complete=True,
        evidence_complete=True,
        timely=False,
        industry_clear=True,
        support_strength=15,
        leasing_strength=30,
        actionable=True,
    )

    assert result.score == 59
    assert result.grade == "C"
    assert result.sheet_name == "政策观察"
    assert result.review_reason == "政策申报已截止"


def test_evaluate_uses_supplied_reference_date_for_expiry_gate() -> None:
    result = evaluate(
        _document(application_end_date=date(2026, 7, 28)),
        _opportunity(),
        reference_date=date(2026, 7, 29),
    )

    assert result.sheet_name == "政策观察"
    assert result.review_reason == "政策申报已截止"


def test_evaluate_routes_policy_without_any_timing_to_observation() -> None:
    result = evaluate(_document(publish_date=None), _opportunity())

    assert result.sheet_name == "政策观察"
    assert result.review_reason == "政策时效信息不明确"


@pytest.mark.parametrize(
    "changes",
    [
        {
            "publish_date": date(2026, 7, 20),
            "application_end_date": date(2026, 7, 19),
        },
        {
            "application_start_date": date(2026, 7, 22),
            "application_end_date": date(2026, 7, 21),
        },
    ],
)
def test_evaluate_routes_contradictory_timing_to_observation(
    changes: dict[str, object],
) -> None:
    result = evaluate(_document(**changes), _opportunity())

    assert result.sheet_name == "政策观察"
    assert result.review_reason == "政策日期存在矛盾"


def test_application_deadline_equal_to_reference_date_is_still_timely() -> None:
    result = evaluate(
        _document(application_end_date=date(2026, 7, 29)),
        _opportunity(),
        reference_date=date(2026, 7, 29),
    )

    assert result.sheet_name == "重点商机"


def test_attachment_parse_failure_routes_opportunity_to_observation() -> None:
    result = evaluate(
        _document(attachment_errors=["附件解析失败（notice.pdf）：PdfReadError"]),
        _opportunity(),
    )

    assert result.sheet_name == "政策观察"
    assert result.review_reason == "附件解析不完整：附件解析失败（notice.pdf）：PdfReadError"


@pytest.mark.parametrize(
    ("document_changes", "opportunity_changes", "expected_reason"),
    [
        ({"title": " "}, {}, "政策追溯信息不完整：政策名称"),
        ({"source_id": ""}, {}, "政策追溯信息不完整：来源标识"),
        ({"source_name": "\n"}, {}, "政策追溯信息不完整：来源名称"),
        ({"raw_text": "  "}, {}, "政策追溯信息不完整：原始正文"),
        ({"normalized_text": "\t"}, {}, "政策追溯信息不完整：规范正文"),
        ({}, {"section_code": ""}, "标准行业分类信息不完整"),
        ({}, {"section_name": " "}, "标准行业分类信息不完整"),
        ({}, {"division_code": "\n"}, "标准行业分类信息不完整"),
        ({}, {"division_name": "\t"}, "标准行业分类信息不完整"),
        ({}, {"business_tags": [" "]}, "缺少有效业务行业标签"),
        ({}, {"scenarios": ["\n"]}, "缺少明确的机会场景"),
    ],
)
def test_evaluate_routes_blank_priority_fields_to_observation(
    document_changes: dict[str, object],
    opportunity_changes: dict[str, object],
    expected_reason: str,
) -> None:
    result = evaluate(_document(**document_changes), _opportunity(**opportunity_changes))

    assert result.sheet_name == "政策观察"
    assert result.review_reason == expected_reason


def test_evaluate_routes_blank_detail_url_to_observation_if_schema_boundary_is_bypassed() -> None:
    document = _document().model_copy(update={"detail_url": ""})

    result = evaluate(document, _opportunity())

    assert result.sheet_name == "政策观察"
    assert result.review_reason == "政策追溯信息不完整：原文链接"


def test_evaluate_routes_evidence_without_location_to_observation_if_schema_is_bypassed() -> None:
    evidence = Evidence(quote="支持设备更新", location="正文字符1-6").model_copy(
        update={"location": " "}
    )

    result = evaluate(_document(), _opportunity(evidence=[evidence]))

    assert result.sheet_name == "政策观察"
    assert result.review_reason == "缺少可定位的行业原文依据"


def test_evaluate_applies_compliance_gate_before_scoring() -> None:
    result = evaluate(_document(), _opportunity(opening_script="政府背书，保证获批"))

    assert result.sheet_name == "政策观察"
    assert result.review_reason == "营销话术含过度承诺或政府背书表达"


def test_evaluate_routes_unverifiable_evidence_to_observation() -> None:
    result = evaluate(
        _document(normalized_text="支持设备更新和技术改造。"),
        _opportunity(evidence=[Evidence(quote="给予百万补贴", location="正文字符1-6")]),
    )

    assert result.sheet_name == "政策观察"
    assert result.review_reason == "缺少可定位的行业原文依据"


def test_evaluate_routes_tampered_evidence_location_to_observation() -> None:
    result = evaluate(
        _document(),
        _opportunity(
            evidence=[Evidence(quote="支持设备更新", location="外部网页第99段")]
        ),
    )

    assert result.sheet_name == "政策观察"
    assert result.review_reason == "缺少可定位的行业原文依据"
