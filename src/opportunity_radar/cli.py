from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from collections.abc import Sequence
from datetime import UTC, date, datetime
from pathlib import Path

from opportunity_radar.analysis.client import (
    MiniMaxAnthropicAnalyzer,
    OpenAICompatibleAnalyzer,
)
from opportunity_radar.collection import (
    collect_batch,
    latest_batch,
    load_batch,
    local_sources,
)
from opportunity_radar.compliance import (
    ComplianceAuditSnapshot,
    ComplianceSource,
    load_compliance_sources,
)
from opportunity_radar.config import RunConfig, SourceConfig, load_sources
from opportunity_radar.diagnostics import configure_logging, safe_url
from opportunity_radar.industry import load_industry_codes
from opportunity_radar.parsing.html import DocumentRetriever
from opportunity_radar.pipeline import run_pipeline
from opportunity_radar.sources.registry import build_sources

LOGGER = logging.getLogger(__name__)

DEFAULT_SOURCES = (
    "miit",
    "ndrc",
    "zhejiang_huiqi",
    "zhejiang_eit",
    "jiangsu_government",
    "jiangsu_eit",
)


def _source_ids(value: str) -> tuple[str, ...]:
    source_ids = tuple(item.strip() for item in value.split(",") if item.strip())
    if not source_ids:
        raise argparse.ArgumentTypeError("at least one source must be selected")
    return source_ids


def _select_compliant_sources(
    requested: tuple[str, ...] | None,
    configured: dict[str, SourceConfig],
    compliance: dict[str, ComplianceSource],
    today: date,
) -> tuple[tuple[str, ...], tuple[ComplianceAuditSnapshot, ...]]:
    requested_ids = requested or tuple(
        source_id
        for source_id, source in configured.items()
        if source.enabled and source_id in compliance
    )
    problems: list[str] = []
    selected: list[str] = []
    audit: list[ComplianceAuditSnapshot] = []
    for source_id in requested_ids:
        if source_id not in compliance:
            problems.append(f"{source_id} (not compliance-registered)")
            continue
        reason = compliance[source_id].blocking_reason(today)
        if reason:
            problems.append(f"{source_id} ({reason})")
            continue
        if source_id not in configured:
            problems.append(f"{source_id} (no adapter configured)")
            continue
        if not configured[source_id].enabled:
            problems.append(f"{source_id} (adapter enabled=false)")
            continue
        rate_limit = compliance[source_id].rate_limit
        if rate_limit is None:  # defensive: verified model validation requires it
            problems.append(f"{source_id} (rate_limit=missing)")
            continue
        pacing_reason = rate_limit.adapter_interval_blocking_reason(
            configured[source_id].request_interval_seconds
        )
        if pacing_reason is not None:
            problems.append(f"{source_id} ({pacing_reason})")
            continue
        try:
            snapshot = compliance[source_id].audit_snapshot(
                configured[source_id].adapter_version,
                today,
            )
        except ValueError as error:
            problems.append(f"{source_id} ({error})")
            continue
        selected.append(source_id)
        audit.append(snapshot)
    if problems:
        raise ValueError("not eligible: " + ", ".join(problems))
    if not selected:
        raise ValueError("no verified enabled compliance source is configured")
    return tuple(selected), tuple(audit)


def _select_development_sources(
    requested: tuple[str, ...] | None,
    configured: dict[str, SourceConfig],
) -> tuple[str, ...]:
    requested_ids = requested or tuple(
        source_id for source_id, source in configured.items() if source.enabled
    )
    problems = [
        f"{source_id} (no adapter configured)"
        if source_id not in configured
        else f"{source_id} (adapter enabled=false)"
        for source_id in requested_ids
        if source_id not in configured or not configured[source_id].enabled
    ]
    if problems:
        raise ValueError("not available for development: " + ", ".join(problems))
    if not requested_ids:
        raise ValueError("no enabled source adapter is configured")
    return requested_ids


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="opportunity-radar")
    subcommands = parser.add_subparsers(dest="command", required=True)
    run = subcommands.add_parser("run", help="collect and analyze official policies")
    for command in (run,):
        command.add_argument("--start-date", type=date.fromisoformat)
        command.add_argument("--end-date", type=date.fromisoformat)
        command.add_argument("--sources", type=_source_ids)

    collect = subcommands.add_parser(
        "collect",
        help="collect official policies into a local batch without using an LLM",
    )
    collect.add_argument("--start-date", type=date.fromisoformat)
    collect.add_argument("--end-date", type=date.fromisoformat)
    collect.add_argument("--sources", type=_source_ids)
    collect.add_argument(
        "--browser",
        choices=("off", "fallback", "always"),
        default="fallback",
        help="use Playwright after ordinary HTTP failure, always, or never",
    )
    collect.add_argument(
        "--headed",
        action="store_true",
        help="show the browser window during Playwright collection",
    )
    collect.add_argument("--max-pages", type=int, default=20)
    collect.add_argument(
        "--browser-channel",
        help="optional installed browser channel such as msedge or chrome",
    )
    collect.add_argument(
        "--dev-unverified-sources",
        action="store_true",
        help="development only: bypass compliance eligibility for configured adapters",
    )

    analyze = subcommands.add_parser(
        "analyze-local",
        help="analyze a previously collected local policy batch",
    )
    analyze.add_argument(
        "--batch",
        type=Path,
        help="batch JSON path; defaults to the latest batch",
    )
    analyze.add_argument(
        "--force",
        action="store_true",
        help="reanalyze every document even if it was analyzed successfully before",
    )

    search = subcommands.add_parser(
        "search-sources",
        help="基于关键词自动发现政府政策信源",
    )
    search.add_argument(
        "--keywords",
        default="all",
        help="关键词标签，逗号分隔；all=全部",
    )
    search.add_argument(
        "--portals",
        default="all",
        help="门户 ID，逗号分隔；all=全部",
    )
    search.add_argument(
        "--mode",
        default="direct-crawl",
        choices=["direct-crawl"],
    )
    search.set_defaults(func=cmd_search_sources)
    return parser


def _build_analyzer() -> MiniMaxAnthropicAnalyzer | OpenAICompatibleAnalyzer:
    provider = os.getenv("OPPORTUNITY_RADAR_LLM_PROVIDER", "openai").strip().lower()
    if provider == "minimax":
        base_url = os.getenv(
            "OPPORTUNITY_RADAR_LLM_BASE_URL",
            "https://api.minimaxi.com/anthropic",
        )
        model = os.getenv("OPPORTUNITY_RADAR_LLM_MODEL", "MiniMax-M3")
        LOGGER.info(
            "初始化分析模型 provider=minimax model=%s base_url=%s",
            model,
            safe_url(base_url),
        )
        return MiniMaxAnthropicAnalyzer(
            base_url,
            os.environ["OPPORTUNITY_RADAR_LLM_API_KEY"],
            model,
        )
    if provider == "openai":
        base_url = os.getenv("OPPORTUNITY_RADAR_LLM_BASE_URL", "https://api.openai.com/v1")
        model = os.environ["OPPORTUNITY_RADAR_LLM_MODEL"]
        LOGGER.info(
            "初始化分析模型 provider=openai model=%s base_url=%s",
            model,
            safe_url(base_url),
        )
        return OpenAICompatibleAnalyzer(
            base_url,
            os.environ["OPPORTUNITY_RADAR_LLM_API_KEY"],
            model,
        )
    raise ValueError(f"unsupported LLM provider: {provider}")


def _analysis_inputs() -> tuple[dict[str, str], list[str]]:
    valid_codes = load_industry_codes(Path("data/industry/gbt_4754_2017.json"))
    business_tags = json.loads(Path("config/business_industries.json").read_text(encoding="utf-8"))
    return valid_codes, business_tags


def build_orchestrator():
    import httpx

    from opportunity_radar.discovery.checker import ComplianceChecker
    from opportunity_radar.discovery.crawler import PortalCrawler
    from opportunity_radar.discovery.keywords import FallbackKeywordSource
    from opportunity_radar.discovery.orchestrator import DiscoveryOrchestrator
    from opportunity_radar.discovery.scorer import ImportanceScorer

    return DiscoveryOrchestrator(
        PortalCrawler(httpx.Client(timeout=30.0)),
        ComplianceChecker(),
        ImportanceScorer(),
        FallbackKeywordSource(),
    )


def cmd_search_sources(args) -> int:
    orch = build_orchestrator()
    tags = None if args.keywords == "all" else args.keywords.split(",")
    ids = None if args.portals == "all" else args.portals.split(",")
    report = orch.run(keyword_tags=tags, portal_ids=ids, mode=args.mode)
    print(
        f"Report: discovery job={report.job_id} candidates={len(report.candidates)} "
        f"restricted={report.stats.get('restricted_stopped', 0)}"
    )
    return 0


def main(argv: Sequence[str] | None = None) -> int | None:
    configure_logging()
    parser = _parser()
    args = parser.parse_args(argv)
    LOGGER.info("CLI 启动 command=%s", args.command)

    if args.command == "analyze-local":
        try:
            batch_path = args.batch or latest_batch(Path("data/normalized/batches"))
            batch = load_batch(batch_path)
            LOGGER.info(
                "读取本地批次 path=%s documents=%d start_date=%s end_date=%s",
                batch_path,
                len(batch.documents),
                batch.start_date,
                batch.end_date,
            )
            sources, retriever = local_sources(batch)
            config = RunConfig(
                batch.start_date,
                batch.end_date,
                tuple(sources),
                compliance_audit=batch.compliance_audit,
                force_reanalyze=args.force,
            )
            analyzer = _build_analyzer()
            valid_codes, business_tags = _analysis_inputs()
        except (KeyError, OSError, TypeError, ValueError) as error:
            parser.error(str(error))
        workbook, report = run_pipeline(
            config,
            sources,
            retriever,
            analyzer,
            valid_codes,
            business_tags,
        )
        print(f"Workbook: {workbook}\nReport: {report}")
        return

    if args.command == "search-sources":
        return args.func(args)

    try:
        configured = load_sources(Path("config/sources.json"))
        development_mode = (
            args.command == "collect" and args.dev_unverified_sources
        )
        if development_mode:
            selected_source_ids = _select_development_sources(
                args.sources,
                configured,
            )
            compliance_audit = ()
            print(
                "WARNING: development collection bypasses compliance eligibility; "
                "do not use this mode for production.",
                file=sys.stderr,
            )
        else:
            compliance = load_compliance_sources(
                Path("config/compliance_sources.json")
            )
            selected_source_ids, compliance_audit = _select_compliant_sources(
                args.sources,
                configured,
                compliance,
                datetime.now(UTC).date(),
            )
        config = RunConfig.from_optional_dates(
            args.start_date,
            args.end_date,
            selected_source_ids,
            compliance_audit,
        )
    except (TypeError, ValueError) as error:
        parser.error(str(error))
    sources = build_sources(
        {source_id: configured[source_id] for source_id in config.source_ids}
    )

    if args.command == "collect":
        browser = None
        if args.browser != "off":
            from opportunity_radar.browser import PlaywrightCollector

            browser = PlaywrightCollector(
                headless=not args.headed,
                max_pages=args.max_pages,
                channel=args.browser_channel,
            )
        batch_path = collect_batch(
            config,
            sources,
            DocumentRetriever(),
            browser=browser,
            browser_mode=args.browser,
            development_mode=development_mode,
        )
        print(f"Batch: {batch_path}")
        return

    try:
        analyzer = _build_analyzer()
    except ValueError as error:
        parser.error(str(error))
    valid_codes, business_tags = _analysis_inputs()
    workbook, report = run_pipeline(
        config,
        sources,
        DocumentRetriever(),
        analyzer,
        valid_codes,
        business_tags,
    )
    print(f"Workbook: {workbook}\nReport: {report}")
