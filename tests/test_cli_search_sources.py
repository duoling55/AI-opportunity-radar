from unittest.mock import patch

from opportunity_radar.cli import main


def test_search_sources_cli_writes_report(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "compliance_sources.json").write_text("[]")
    (tmp_path / "config" / "discovery_portals.json").write_text("[]")
    (tmp_path / "config" / "discovery_keywords.json").write_text("[]")

    fake_report = {
        "job_id": "disc-test",
        "candidates": [],
        "stats": {},
        "errors": [],
        "portals_scanned": [],
        "keywords_used": [],
        "started_at": "",
        "finished_at": "",
    }
    with patch("opportunity_radar.cli.build_orchestrator") as bo:
        bo.return_value.run.return_value = type("R", (), fake_report)()
        rc = main(["search-sources", "--keywords", "all", "--portals", "all"])
    assert rc == 0
    bo.return_value.run.assert_called_once_with(
        keyword_tags=None, portal_ids=None, mode="direct-crawl"
    )


def test_search_sources_cli_passes_keyword_and_portal_filters(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "compliance_sources.json").write_text("[]")
    (tmp_path / "config" / "discovery_portals.json").write_text("[]")
    (tmp_path / "config" / "discovery_keywords.json").write_text("[]")

    fake_report = {
        "job_id": "disc-filter",
        "candidates": ["gov"],
        "stats": {"restricted_stopped": 1},
        "errors": [],
        "portals_scanned": [],
        "keywords_used": [],
        "started_at": "",
        "finished_at": "",
    }
    with patch("opportunity_radar.cli.build_orchestrator") as bo:
        bo.return_value.run.return_value = type("R", (), fake_report)()
        rc = main(
            [
                "search-sources",
                "--keywords",
                "leasing,equipment",
                "--portals",
                "gov,zj",
            ]
        )
    assert rc == 0
    bo.return_value.run.assert_called_once_with(
        keyword_tags=["leasing", "equipment"],
        portal_ids=["gov", "zj"],
        mode="direct-crawl",
    )
