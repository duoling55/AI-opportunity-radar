from datetime import UTC, date, datetime
from pathlib import Path

import opportunity_radar.config as config_module
from opportunity_radar.compliance import load_compliance_sources
from opportunity_radar.config import RunConfig, load_sources


def test_load_sources_and_default_window() -> None:
    sources = load_sources(Path("config/sources.json"))
    assert {
        "miit",
        "ndrc",
        "zhejiang_huiqi",
        "zhejiang_eit",
        "jiangsu_government",
        "jiangsu_eit",
    } <= set(sources)
    assert sources["miit"].allowed_domains == ("www.miit.gov.cn",)
    config = RunConfig.from_optional_dates(None, None, source_ids=("miit",))
    assert config.start_date < config.end_date
    assert (config.end_date - config.start_date).days == 30


def test_default_end_date_uses_utc_clock(monkeypatch) -> None:
    class FixedUtcClock:
        @staticmethod
        def now(tz: object) -> datetime:
            assert tz is UTC
            return datetime(2026, 7, 29, 0, 30, tzinfo=UTC)

    monkeypatch.setattr(config_module, "datetime", FixedUtcClock)

    config = RunConfig.from_optional_dates(None, None, source_ids=("miit",))

    assert config.end_date == date(2026, 7, 29)


def test_explicit_single_day_window_is_inclusive() -> None:
    config = RunConfig.from_optional_dates(
        date(2026, 7, 29),
        date(2026, 7, 29),
        source_ids=("miit",),
    )

    assert config.start_date == config.end_date == date(2026, 7, 29)


def test_candidate_sources_are_not_present_in_automatic_source_config() -> None:
    automatic = load_sources(Path("config/sources.json"))
    candidates = load_compliance_sources(Path("config/compliance_sources.json"))

    assert not (set(automatic) & set(candidates))
