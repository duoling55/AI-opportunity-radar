"""端到端集成：promote 前后采集门控与 sources.json 同步。"""

import json

from opportunity_radar.collection import filter_collectable
from opportunity_radar.discovery.service import DiscoveryService


def _candidate_record(source_id: str = "gov_a") -> dict:
    return {
        "source_id": source_id,
        "display_name": "A",
        "region": "国家",
        "phase": "candidate",
        "enabled": False,
        "official_urls": ["https://www.gov.cn/zc/"],
        "origin": "discovery",
        "discovery": {
            "keywords": [],
            "discovered_at": "2026-08-01",
            "portal_seed_id": "g",
            "admin_level": "国家",
            "sample_policies": [],
            "snapshots": [],
            "check_result": "pass",
            "check_details": {},
            "recommendation": "建议启用",
            "priority_score": 85,
            "priority_level": "高",
            "score_breakdown": [],
        },
    }


def test_promoted_source_is_collectable_and_unverified_is_not(tmp_path) -> None:
    comp = tmp_path / "compliance_sources.json"
    srcs = tmp_path / "sources.json"
    comp.write_text(json.dumps([_candidate_record()], ensure_ascii=False), encoding="utf-8")
    srcs.write_text("[]", encoding="utf-8")

    svc = DiscoveryService(compliance_path=str(comp), sources_path=str(srcs))

    # 未 promote 前，候选不可采集（门控拦截 candidate）
    selectable = filter_collectable(
        [{"source_id": "gov_a", "origin": "discovery"}], compliance_path=str(comp)
    )
    assert selectable == []

    # promote 后同步 sources.json 且可采集
    svc.promote("gov_a", reviewer="admin")
    srcs_data = json.loads(srcs.read_text(encoding="utf-8"))
    selectable = filter_collectable(srcs_data, compliance_path=str(comp))
    assert [s["source_id"] for s in selectable] == ["gov_a"]


def test_rejected_source_is_not_collectable(tmp_path) -> None:
    comp = tmp_path / "compliance_sources.json"
    srcs = tmp_path / "sources.json"
    comp.write_text(json.dumps([_candidate_record()], ensure_ascii=False), encoding="utf-8")
    srcs.write_text("[]", encoding="utf-8")

    svc = DiscoveryService(compliance_path=str(comp), sources_path=str(srcs))
    svc.review("gov_a", action="reject", reason="证据不足", reviewer="admin")

    # 驳回后 phase=retired，门控拦截
    selectable = filter_collectable(
        [{"source_id": "gov_a", "origin": "discovery"}], compliance_path=str(comp)
    )
    assert selectable == []
