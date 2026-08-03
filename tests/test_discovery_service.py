import json
from datetime import date

import pytest

from opportunity_radar.discovery.service import DiscoveryService


def _candidate_record(
    source_id: str = "gov_disc",
    phase: str = "candidate",
    check_result: str = "pass",
    display_name: str = "国务院",
) -> dict:
    meta = {
        "keywords": ["设备更新"],
        "discovered_at": str(date(2026, 8, 1)),
        "portal_seed_id": "gov",
        "admin_level": "国家",
        "sample_policies": [],
        "snapshots": [],
        "check_result": check_result,
        "check_details": {},
        "recommendation": "建议启用",
        "priority_score": 85,
        "priority_level": "高",
        "score_breakdown": [],
    }
    return {
        "source_id": source_id,
        "display_name": display_name,
        "region": "国家",
        "phase": phase,
        "enabled": False,
        "official_urls": ["https://www.gov.cn/zc/"],
        "origin": "discovery",
        "discovery": meta,
    }


def _write(tmp_path, records: list[dict]) -> tuple:
    comp = tmp_path / "compliance_sources.json"
    srcs = tmp_path / "sources.json"
    comp.write_text(json.dumps(records, ensure_ascii=False), encoding="utf-8")
    srcs.write_text("[]", encoding="utf-8")
    return comp, srcs


def test_list_candidates_returns_only_discovery(tmp_path) -> None:
    comp, srcs = _write(
        tmp_path,
        [
            _candidate_record(),
            {"source_id": "manual_one", "origin": "manual", "phase": "candidate"},
        ],
    )
    svc = DiscoveryService(compliance_path=str(comp), sources_path=str(srcs))
    cands = svc.list_candidates()
    assert len(cands) == 1
    assert cands[0]["source_id"] == "gov_disc"


def test_list_candidates_dedup_keeps_latest(tmp_path) -> None:
    older = _candidate_record()
    newer = _candidate_record()
    newer["discovery"]["priority_score"] = 99
    comp, srcs = _write(tmp_path, [older, newer])
    svc = DiscoveryService(compliance_path=str(comp), sources_path=str(srcs))
    cands = svc.list_candidates()
    assert len(cands) == 1
    assert cands[0]["discovery"]["priority_score"] == 99


def test_list_candidates_excludes_verified_and_retired(tmp_path) -> None:
    verified = _candidate_record(source_id="v", phase="verified")
    retired = _candidate_record(source_id="r", phase="retired")
    cand = _candidate_record(source_id="c", phase="candidate")
    comp, srcs = _write(tmp_path, [verified, retired, cand])
    svc = DiscoveryService(compliance_path=str(comp), sources_path=str(srcs))
    cands = svc.list_candidates()
    assert [c["source_id"] for c in cands] == ["c"]


def test_promote_moves_to_verified_and_syncs_sources(tmp_path) -> None:
    comp, srcs = _write(tmp_path, [_candidate_record()])
    svc = DiscoveryService(compliance_path=str(comp), sources_path=str(srcs))
    svc.promote("gov_disc", reviewer="admin")
    comp_data = json.loads(comp.read_text(encoding="utf-8"))
    assert comp_data[0]["phase"] == "verified"
    assert comp_data[0]["enabled"] is True
    srcs_data = json.loads(srcs.read_text(encoding="utf-8"))
    assert srcs_data[0]["source_id"] == "gov_disc"
    assert srcs_data[0]["origin"] == "discovery"
    assert srcs_data[0]["adapter_version"] == "generic"
    assert srcs_data[0]["enabled"] is True


def test_promote_not_recommended_requires_override(tmp_path) -> None:
    comp, srcs = _write(tmp_path, [_candidate_record(check_result="not_recommended")])
    svc = DiscoveryService(compliance_path=str(comp), sources_path=str(srcs))
    with pytest.raises(ValueError, match="not_recommended"):
        svc.promote("gov_disc", reviewer="admin")
    svc.promote("gov_disc", reviewer="admin", override_not_recommended=True)
    assert json.loads(comp.read_text(encoding="utf-8"))[0]["phase"] == "verified"


def test_promote_rejects_non_candidate(tmp_path) -> None:
    comp, srcs = _write(tmp_path, [_candidate_record(phase="verified")])
    svc = DiscoveryService(compliance_path=str(comp), sources_path=str(srcs))
    with pytest.raises(ValueError, match="非候选"):
        svc.promote("gov_disc", reviewer="admin")


def test_reject_retires_source(tmp_path) -> None:
    comp, srcs = _write(tmp_path, [_candidate_record()])
    svc = DiscoveryService(compliance_path=str(comp), sources_path=str(srcs))
    svc.review("gov_disc", action="reject", reason="证据不足", reviewer="admin")
    rec = json.loads(comp.read_text(encoding="utf-8"))[0]
    assert rec["phase"] == "retired"
    assert rec["enabled"] is False


def test_review_confirm_forwards_to_promote(tmp_path) -> None:
    comp, srcs = _write(tmp_path, [_candidate_record()])
    svc = DiscoveryService(compliance_path=str(comp), sources_path=str(srcs))
    svc.review("gov_disc", action="confirm", reason=None, reviewer="admin")
    rec = json.loads(comp.read_text(encoding="utf-8"))[0]
    assert rec["phase"] == "verified"
    assert rec["enabled"] is True
