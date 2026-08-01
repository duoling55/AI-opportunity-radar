import json
from unittest.mock import MagicMock, patch

from opportunity_radar import ui_server


def test_candidates_payload_calls_service() -> None:
    svc = MagicMock()
    svc.list_candidates.return_value = [{"source_id": "g", "origin": "discovery"}]
    with patch.object(ui_server, "_discovery_service", return_value=svc):
        result = ui_server._discovery_candidates_payload()
    assert result == [{"source_id": "g", "origin": "discovery"}]


def test_candidate_payload_returns_single_or_empty() -> None:
    svc = MagicMock()
    svc.get_candidate.return_value = {"source_id": "g"}
    with patch.object(ui_server, "_discovery_service", return_value=svc):
        assert ui_server._discovery_candidate_payload("g") == {"source_id": "g"}
    svc.get_candidate.return_value = None
    with patch.object(ui_server, "_discovery_service", return_value=svc):
        assert ui_server._discovery_candidate_payload("missing") == {}


def test_promote_payload_forwards_to_service() -> None:
    svc = MagicMock()
    svc.promote.return_value = {"source_id": "g", "phase": "verified"}
    with patch.object(ui_server, "_discovery_service", return_value=svc):
        result = ui_server._discovery_promote("g", {"reviewer": "admin"})
    svc.promote.assert_called_once_with(
        "g", reviewer="admin", override_not_recommended=False
    )
    assert result["phase"] == "verified"


def test_promote_payload_passes_override() -> None:
    svc = MagicMock()
    svc.promote.return_value = {"phase": "verified"}
    with patch.object(ui_server, "_discovery_service", return_value=svc):
        ui_server._discovery_promote("g", {"reviewer": "admin", "override_not_recommended": True})
    svc.promote.assert_called_once_with(
        "g", reviewer="admin", override_not_recommended=True
    )


def test_review_payload_forwards_to_service() -> None:
    svc = MagicMock()
    svc.review.return_value = {"phase": "retired"}
    with patch.object(ui_server, "_discovery_service", return_value=svc):
        ui_server._discovery_review(
            "g", {"action": "reject", "reason": "证据不足", "reviewer": "a"}
        )
    svc.review.assert_called_once_with(
        "g", action="reject", reason="证据不足", reviewer="a", comment=""
    )


def test_start_search_builds_search_sources_job(monkeypatch) -> None:
    captured: dict = {}
    fake_job = MagicMock(job_id="job-1", label="信源搜索")

    def fake_start(label, args, env):
        captured["label"] = label
        captured["args"] = args
        return fake_job

    monkeypatch.setattr(ui_server, "_start_job", fake_start)
    monkeypatch.setattr(
        ui_server, "_job_payload", lambda job: {"job_id": job.job_id, "label": job.label}
    )
    result = ui_server._start_discovery_search(
        {"keywords": "技改投资", "portals": "gov_cn"}
    )
    assert captured["label"] == "信源搜索"
    assert captured["args"][0] == "search-sources"
    assert "--keywords" in captured["args"]
    assert "技改投资" in captured["args"]
    assert "gov_cn" in captured["args"]
    assert result == {"job_id": "job-1", "label": "信源搜索"}


def test_start_search_defaults_all(monkeypatch) -> None:
    captured: dict = {}
    monkeypatch.setattr(
        ui_server,
        "_start_job",
        lambda label, args, env: captured.update(label=label, args=args) or MagicMock(job_id="j"),
    )
    monkeypatch.setattr(ui_server, "_job_payload", lambda job: {"job_id": job.job_id})
    ui_server._start_discovery_search({})
    assert captured["args"] == ["search-sources", "--keywords", "all", "--portals", "all"]


def test_keywords_payload_returns_unique_tags(tmp_path, monkeypatch) -> None:
    path = tmp_path / "keywords.json"
    path.write_text(
        json.dumps(
            [
                {"text": "设备更新", "tag": "技改投资"},
                {"text": "技术改造", "tag": "技改投资"},
                {"text": "融资租赁", "tag": "融资支持"},
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(ui_server, "DISCOVERY_KEYWORDS_PATH", path)
    assert ui_server._discovery_keywords_payload() == ["技改投资", "融资支持"]


def test_reports_payload_lists_report_files(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(ui_server, "DISCOVERY_REPORT_DIRECTORY", tmp_path)
    (tmp_path / "disc-aaa-report.json").write_text(
        json.dumps({"job_id": "disc-aaa", "candidates": ["g"]}), encoding="utf-8"
    )
    (tmp_path / "not-a-report.txt").write_text("x", encoding="utf-8")
    reports = ui_server._discovery_reports_payload()
    assert len(reports) == 1
    assert reports[0]["data"]["job_id"] == "disc-aaa"
    assert reports[0]["name"] == "disc-aaa-report.json"
