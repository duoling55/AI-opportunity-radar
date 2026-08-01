from __future__ import annotations

import logging
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from opportunity_radar.browser import _assert_allowed, _assert_unrestricted
from opportunity_radar.collection import (
    collect_batch,
    load_batch,
    local_sources,
)
from opportunity_radar.config import RunConfig, SourceConfig
from opportunity_radar.models import PolicyCandidate, PolicyDocument


class _Source:
    def discover(self, start: date, end: date) -> list[PolicyCandidate]:
        return [
            PolicyCandidate(
                source_id="fixture",
                title="设备更新通知",
                detail_url="https://example.gov.cn/policy",
                published_at=date(2026, 7, 20),
            )
        ]


class _Retriever:
    def fetch_document(
        self,
        source: _Source,
        candidate: PolicyCandidate,
        collected_at: datetime,
        raw_dir: Path,
    ) -> PolicyDocument:
        del source, collected_at, raw_dir
        return PolicyDocument(
            policy_id="fixture-policy",
            source_id=candidate.source_id,
            source_name="测试来源",
            region="全国",
            title=candidate.title,
            detail_url=candidate.detail_url,
            publish_date=candidate.published_at,
            raw_text="支持设备更新。",
            normalized_text="支持设备更新。",
            collected_at=datetime(2026, 7, 30, tzinfo=UTC),
            content_hash="content-v1",
            snapshot_path="data/raw/policy.html",
        )


class _EmptySource:
    def discover(self, start: date, end: date) -> list[PolicyCandidate]:
        del start, end
        return []


class _ApiSource(_Source):
    prefer_direct_http = True


class _BrowserThatMustNotCollect:
    def __init__(self) -> None:
        self.closed = False

    def discover(self, source: object, start: date, end: date) -> list[PolicyCandidate]:
        del source, start, end
        raise AssertionError("API source must not be collected through the browser")

    def fetch_document(
        self,
        source: object,
        candidate: PolicyCandidate,
        collected_at: datetime,
        raw_dir: Path,
    ) -> PolicyDocument:
        del source, candidate, collected_at, raw_dir
        raise AssertionError("API source detail must not be fetched through the browser")

    def close(self) -> None:
        self.closed = True


def _config(tmp_path: Path) -> RunConfig:
    return RunConfig(
        date(2026, 7, 1),
        date(2026, 7, 30),
        ("fixture",),
        output_dir=tmp_path / "outputs",
        state_path=tmp_path / "state" / "analysis.sqlite3",
        raw_dir=tmp_path / "raw",
        normalized_dir=tmp_path / "normalized",
    )


def test_collect_batch_round_trips_and_skips_unchanged_documents(
    tmp_path: Path,
) -> None:
    config = _config(tmp_path)
    first_path = collect_batch(
        config,
        {"fixture": _Source()},
        _Retriever(),
        browser_mode="off",
        development_mode=True,
    )
    second_path = collect_batch(
        config,
        {"fixture": _Source()},
        _Retriever(),
        browser_mode="off",
    )

    first = load_batch(first_path)
    second = load_batch(second_path)
    assert [document.title for document in first.documents] == ["设备更新通知"]
    assert first.report.collected == 1
    assert first.development_mode is True
    assert second.documents == ()
    assert second.report.skipped == 1
    assert second.development_mode is False

    sources, retriever = local_sources(first)
    candidates = sources["fixture"].discover(first.start_date, first.end_date)
    restored = retriever.fetch_document(
        sources["fixture"],
        candidates[0],
        datetime.now(UTC),
        tmp_path,
    )
    assert restored.content_hash == "content-v1"


def test_collect_batch_logs_an_actionable_warning_when_discovery_is_empty(
    caplog: pytest.LogCaptureFixture,
    tmp_path: Path,
) -> None:
    caplog.set_level(logging.WARNING, logger="opportunity_radar.collection")

    batch_path = collect_batch(
        _config(tmp_path),
        {"fixture": _EmptySource()},
        _Retriever(),
        browser_mode="off",
        development_mode=True,
    )

    assert load_batch(batch_path).report.discovered == 0
    assert "信源未发现候选 source_id=fixture" in caplog.text
    assert "请检查列表地址、页面选择器和日期范围" in caplog.text


def test_collect_batch_prefers_an_api_source_when_browser_mode_is_always(tmp_path: Path) -> None:
    browser = _BrowserThatMustNotCollect()

    batch_path = collect_batch(
        _config(tmp_path),
        {"fixture": _ApiSource()},
        _Retriever(),
        browser=browser,
        browser_mode="always",
    )

    assert load_batch(batch_path).report.collected == 1
    assert browser.closed is True


@pytest.mark.parametrize("status", [401, 403, 429])
def test_browser_collector_stops_on_restricted_status(status: int) -> None:
    with pytest.raises(PermissionError):
        _assert_unrestricted(status)


def test_browser_collector_stops_on_verification_page() -> None:
    with pytest.raises(PermissionError):
        _assert_unrestricted(200, "<title>请输入验证码</title>")


def test_browser_collector_rejects_off_domain_navigation() -> None:
    with pytest.raises(ValueError):
        _assert_allowed(
            "https://attacker.example/policy",
            ("example.gov.cn",),
        )


def test_development_collection_bypasses_compliance_without_using_llm(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    from opportunity_radar import cli

    configured = {
        "fixture": SourceConfig(
            "fixture",
            "测试来源",
            "全国",
            ("https://example.gov.cn/list",),
            ("example.gov.cn",),
            adapter_version="dev",
        )
    }
    captured: dict[str, object] = {}
    monkeypatch.setattr(cli, "load_sources", lambda path: configured)
    monkeypatch.setattr(
        cli,
        "load_compliance_sources",
        lambda path: (_ for _ in ()).throw(
            AssertionError("development mode must not load compliance")
        ),
    )
    monkeypatch.setattr(
        cli,
        "build_sources",
        lambda configs: {"fixture": _Source()},
    )
    monkeypatch.setattr(cli, "DocumentRetriever", lambda: _Retriever())

    def fake_collect(*args: object, **kwargs: object) -> Path:
        captured.update(kwargs)
        return tmp_path / "batch.json"

    monkeypatch.setattr(cli, "collect_batch", fake_collect)

    cli.main(
        [
            "collect",
            "--sources",
            "fixture",
            "--browser",
            "off",
            "--dev-unverified-sources",
        ]
    )

    assert captured["development_mode"] is True
    assert "development collection bypasses compliance" in capsys.readouterr().err
