import json
from copy import deepcopy
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from opportunity_radar.compliance import (
    ComplianceSource,
    RateLimitPolicy,
    load_compliance_sources,
)


def _verified_record() -> dict[str, Any]:
    return {
        "source_id": "verified",
        "display_name": "已核验来源",
        "phase": "verified",
        "enabled": True,
        "official_urls": ["https://example.gov.cn/policies"],
        "data_access_mode": "restricted_dataset_api",
        "terms": "书面许可允许按核验字段和限频自动访问。",
        "terms_confirmed": True,
        "registration": "completed",
        "registration_completed": True,
        "authorization": "written_permission",
        "rate_limit": {
            "max_requests": 12,
            "period_seconds": 60,
            "minimum_interval_seconds": 5,
        },
        "selected_data_scope": "惠企政策数据集 v1",
        "field_permission_confirmed": True,
        "available_fields": ["标题", "发布日期"],
        "evidence_url": "https://example.gov.cn/permission/record",
        "verified_at": "2026-07-01",
        "owner": "policy-ops",
        "review_due_at": "2026-09-29",
        "verification_notes": "2026-07-01 完成核验。",
    }


def _write_registry(tmp_path: Path, record: dict[str, Any]) -> Path:
    path = tmp_path / "compliance.json"
    path.write_text(json.dumps([record], ensure_ascii=False), encoding="utf-8")
    return path


def test_initial_registry_contains_only_disabled_candidates() -> None:
    sources = load_compliance_sources(Path("config/compliance_sources.json"))

    assert set(sources) == {
        "state_council_policy_library",
        "zhejiang_open_data",
        "jiangsu_benefit_policy",
    }
    assert all(source.phase == "candidate" for source in sources.values())
    assert all(source.enabled is False for source in sources.values())
    assert all(source.rate_limit is None for source in sources.values())
    assert all(source.owner == "unassigned" for source in sources.values())
    assert all(source.terms_confirmed is None for source in sources.values())
    assert all(source.registration_completed is None for source in sources.values())
    assert all(source.selected_data_scope == "unknown" for source in sources.values())
    assert all(source.field_permission_confirmed is None for source in sources.values())


def test_candidate_may_retain_unknown_verification_dimensions() -> None:
    source = ComplianceSource(
        source_id="candidate",
        display_name="候选来源",
        phase="candidate",
        enabled=False,
        terms="自动访问条款待确认。",
        terms_confirmed=None,
        registration="unknown",
        registration_completed=None,
        authorization="unknown",
        rate_limit=None,
        selected_data_scope="unknown",
        field_permission_confirmed=None,
        evidence_url="https://example.gov.cn/evidence",
        verified_at=None,
        review_due_at=date(2026, 10, 27),
        owner="unassigned",
        available_fields=(),
    )

    assert source.blocking_reason(date(2026, 7, 29)) == "phase=candidate"


def test_fully_confirmed_verified_source_is_eligible(tmp_path: Path) -> None:
    source = load_compliance_sources(_write_registry(tmp_path, _verified_record()))[
        "verified"
    ]

    assert source.blocking_reason(date(2026, 7, 29)) is None


@pytest.mark.parametrize(
    ("policy", "expected"),
    [
        (RateLimitPolicy(12, 60, 1), 5.0),
        (RateLimitPolicy(12, 60, 10), 10.0),
    ],
)
def test_rate_policy_derives_conservative_required_adapter_interval(
    policy: RateLimitPolicy,
    expected: float,
) -> None:
    assert policy.required_adapter_interval_seconds() == expected


@pytest.mark.parametrize(
    ("mutation", "expected_field"),
    [
        ({"terms": ""}, "terms"),
        ({"terms_confirmed": False}, "terms_confirmed"),
        ({"terms_confirmed": "true"}, "terms_confirmed"),
        ({"registration": "pending"}, "registration"),
        ({"registration_completed": False}, "registration_completed"),
        ({"registration_completed": "true"}, "registration_completed"),
        ({"authorization": "oauth_magic"}, "authorization"),
        ({"authorization": "unknown"}, "authorization"),
        ({"rate_limit": "1 request per 5 seconds"}, "rate_limit"),
        (
            {
                "rate_limit": {
                    "max_requests": 0,
                    "period_seconds": 60,
                    "minimum_interval_seconds": 5,
                }
            },
            "rate_limit.max_requests",
        ),
        ({"selected_data_scope": "TBD"}, "selected_data_scope"),
        ({"field_permission_confirmed": False}, "field_permission_confirmed"),
        ({"field_permission_confirmed": "true"}, "field_permission_confirmed"),
        ({"available_fields": []}, "available_fields"),
        ({"available_fields": ["标题", "pending"]}, "available_fields"),
        ({"evidence_url": "http://example.gov.cn/evidence"}, "evidence_url"),
        ({"evidence_url": "TBD"}, "evidence_url"),
        ({"owner": "unassigned"}, "owner"),
        ({"owner": " unassigned "}, "owner"),
        ({"owner": "pending"}, "owner"),
        (
            {
                "rate_limit": {
                    "max_requests": 12,
                    "period_seconds": 60,
                    "minimum_interval_seconds": float("nan"),
                }
            },
            "rate_limit.minimum_interval_seconds",
        ),
        ({"verified_at": ""}, "verified_at"),
        ({"verified_at": "2026/07/01"}, "verified_at"),
        ({"review_due_at": "2026-06-30"}, "review_due_at"),
        ({"review_due_at": "2026-09-30"}, "review_due_at"),
        ({"phase": "approved"}, "phase"),
        ({"enabled": 1}, "enabled"),
        ({"enabled": "true"}, "enabled"),
    ],
)
def test_verified_registry_rejects_each_malformed_or_unconfirmed_dimension(
    tmp_path: Path,
    mutation: dict[str, Any],
    expected_field: str,
) -> None:
    record = deepcopy(_verified_record())
    record.update(mutation)

    with pytest.raises(ValueError, match=expected_field):
        load_compliance_sources(_write_registry(tmp_path, record))


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("phase", "pending"),
        ("enabled", "false"),
        ("registration", "TBD"),
        ("authorization", ""),
        ("selected_data_scope", "pending"),
        ("evidence_url", "not-a-url"),
        ("owner", ""),
        ("review_due_at", ""),
    ],
)
def test_candidate_registry_rejects_malformed_nonempty_and_structural_values(
    tmp_path: Path,
    field: str,
    value: object,
) -> None:
    record = json.loads(
        Path("config/compliance_sources.json").read_text(encoding="utf-8")
    )[0]
    record[field] = value

    with pytest.raises(ValueError, match=field):
        load_compliance_sources(_write_registry(tmp_path, record))
