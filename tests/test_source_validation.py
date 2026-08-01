from __future__ import annotations

import json
from pathlib import Path

import pytest

from opportunity_radar import ui_server
from opportunity_radar.collection import filter_collectable


def _miit() -> dict:
    return {
        "source_id": "miit",
        "display_name": "工信部",
        "region": "全国",
        "list_urls": ["https://www.miit.gov.cn/xwfb/zxzc/index.html"],
        "allowed_domains": ["www.miit.gov.cn"],
        "request_interval_seconds": 1.5,
        "adapter_version": "1.0.2",
        "origin": "manual",
    }


def _discovery() -> dict:
    return {
        "source_id": "gov_disc",
        "display_name": "发现",
        "region": "国家",
        "list_urls": ["https://www.gov.cn/zhengce/"],
        "allowed_domains": ["www.gov.cn"],
        "request_interval_seconds": 1.5,
        "adapter_version": "generic",
        "origin": "discovery",
    }


def _write_sources(tmp_path: Path, records: list[dict]) -> Path:
    path = tmp_path / "sources.json"
    path.write_text(json.dumps(records, ensure_ascii=False), encoding="utf-8")
    return path


def test_source_payload_includes_origin() -> None:
    payload = ui_server._source_payload()
    assert payload
    assert all("origin" in item for item in payload)


def test_validate_allows_new_discovery_source(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(ui_server, "SOURCE_CONFIG_PATH", _write_sources(tmp_path, [_miit()]))
    payload = ui_server._validate_sources([_miit(), _discovery()])
    ids = [item["source_id"] for item in payload]
    assert "gov_disc" in ids
    discovery = next(item for item in payload if item["source_id"] == "gov_disc")
    assert discovery["origin"] == "discovery"
    assert discovery["adapter_version"] == "generic"


def test_validate_rejects_new_manual_source(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(ui_server, "SOURCE_CONFIG_PATH", _write_sources(tmp_path, [_miit()]))
    bad = {
        "source_id": "random",
        "display_name": "随机",
        "region": "全国",
        "list_urls": ["https://random.example/"],
        "allowed_domains": ["random.example"],
        "request_interval_seconds": 1.5,
        "adapter_version": "unregistered",
        "origin": "manual",
    }
    with pytest.raises(ValueError, match="仅允许新增"):
        ui_server._validate_sources([_miit(), bad])


def test_validate_rejects_deleting_existing_source(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(ui_server, "SOURCE_CONFIG_PATH", _write_sources(tmp_path, [_miit(), _discovery()]))
    with pytest.raises(ValueError, match="不能在此页面删除已有信源"):
        ui_server._validate_sources([_miit()])


def test_filter_collectable_excludes_candidate(tmp_path: Path) -> None:
    comp = tmp_path / "compliance_sources.json"
    comp.write_text(
        json.dumps(
            [
                {"source_id": "verified_gov", "origin": "discovery", "phase": "verified", "enabled": True},
                {"source_id": "cand_gov", "origin": "discovery", "phase": "candidate", "enabled": False},
            ]
        ),
        encoding="utf-8",
    )
    sources = [
        {"source_id": "verified_gov", "origin": "discovery"},
        {"source_id": "cand_gov", "origin": "discovery"},
        {"source_id": "miit", "origin": "manual"},
    ]
    selectable = filter_collectable(sources, compliance_path=str(comp))
    ids = [s["source_id"] for s in selectable]
    assert "verified_gov" in ids
    assert "cand_gov" not in ids
    assert "miit" in ids


def test_filter_collectable_without_compliance_file_passes_all(tmp_path: Path) -> None:
    sources = [{"source_id": "miit", "origin": "manual"}]
    assert filter_collectable(sources, compliance_path=str(tmp_path / "missing.json")) == sources
