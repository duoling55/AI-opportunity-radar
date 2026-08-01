from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import replace
from datetime import UTC, date, datetime
from pathlib import Path
from time import perf_counter

import httpx

from opportunity_radar.analysis.client import Analyzer
from opportunity_radar.config import RunConfig
from opportunity_radar.export.excel import ExportRow, export_workbook
from opportunity_radar.export.report import RunReport, write_report
from opportunity_radar.models import (
    IndustryOpportunity,
    PolicyAnalysis,
    PolicyDocument,
)
from opportunity_radar.normalization import cross_source_key, normalize_text
from opportunity_radar.parsing.html import DocumentRetriever
from opportunity_radar.quality.scoring import QualityResult, evaluate
from opportunity_radar.quality.scripts import (
    DISCLAIMER,
    append_disclaimer,
    is_compliant_script,
)
from opportunity_radar.sources.base import PolicySource
from opportunity_radar.state import StateStore

LOGGER = logging.getLogger(__name__)


def _increment(report: RunReport, field: str, amount: int = 1) -> RunReport:
    return replace(report, **{field: getattr(report, field) + amount})


def _document_values(
    document: PolicyDocument,
    analyzed_at: datetime,
) -> dict[str, str | int | float | date | datetime]:
    source_links = [str(document.detail_url), *(str(url) for url in document.supplementary_urls)]
    return {
        "政策名称": document.title,
        "适用地区": document.region,
        "发布机构": document.publisher or "",
        "政策文号": document.document_number or "",
        "发布日期": document.publish_date or "",
        "申报开始日期": document.application_start_date or "",
        "申报截止日期": document.application_end_date or "",
        "政策原文链接": "、".join(source_links),
        "附件链接": "、".join(str(url) for url in document.attachment_urls),
        "数据来源": document.source_name,
        "采集时间": document.collected_at.replace(tzinfo=None),
        "AI 分析时间": analyzed_at.replace(tzinfo=None),
        "免责声明": DISCLAIMER,
    }


def _analysis_values(
    document: PolicyDocument,
    analysis: PolicyAnalysis,
    analyzed_at: datetime,
) -> dict[str, str | int | float | date | datetime]:
    values = _document_values(document, analyzed_at)
    values.update(
        {
            "政策摘要": analysis.summary,
            "支持方向": analysis.support_direction,
            "适用企业条件": analysis.eligible_conditions or "",
            "风险与限制": analysis.risk_notes or "",
        }
    )
    return values


def _opportunity_row(
    document: PolicyDocument,
    analysis: PolicyAnalysis,
    opportunity: IndustryOpportunity,
    quality: QualityResult,
    analyzed_at: datetime,
) -> ExportRow:
    values = _analysis_values(document, analysis, analyzed_at)
    values.update(
        {
            "商机等级": quality.grade,
            "商机评分": quality.score,
            "国标行业门类名称": opportunity.section_name,
            "国标行业门类代码": opportunity.section_code,
            "国标行业大类名称": opportunity.division_name,
            "国标行业大类代码": opportunity.division_code,
            "业务行业标签": "、".join(opportunity.business_tags),
            "行业判断置信度": opportunity.confidence,
            "机会场景": "、".join(opportunity.scenarios),
            "融资租赁关联度": opportunity.leasing_relevance,
            "推荐理由": opportunity.leasing_relevance,
            "评分理由": quality.review_reason or "",
            "政策原文依据": "\n".join(item.quote for item in opportunity.evidence),
            "依据位置": "\n".join(item.location for item in opportunity.evidence),
            "推荐动作": opportunity.recommended_action,
            "行业营销开场白": (
                append_disclaimer(opportunity.opening_script)
                if is_compliant_script(opportunity.opening_script)
                else DISCLAIMER
            ),
            "复核原因": quality.review_reason or "",
        }
    )
    return ExportRow(quality.sheet_name, values)


def _benefit_observation_row(
    document: PolicyDocument,
    analysis: PolicyAnalysis,
    analyzed_at: datetime,
) -> ExportRow:
    values = _analysis_values(document, analysis, analyzed_at)
    values.update(
        {
            "商机等级": "观察",
            "商机评分": 0,
            "国标行业门类名称": "待复核",
            "国标行业门类代码": "待复核",
            "国标行业大类名称": "待复核",
            "国标行业大类代码": "待复核",
            "复核原因": "惠企政策未识别到可验证的机会行业",
        }
    )
    return ExportRow("政策观察", values)


def _analysis_failure_observation_row(
    document: PolicyDocument,
    error: Exception,
    analyzed_at: datetime,
) -> ExportRow:
    context = (document.normalized_text.strip() or document.raw_text.strip())[:32000]
    error_detail = str(error).strip() or "无错误详情"
    values = _document_values(document, analyzed_at)
    values.update(
        {
            "商机等级": "观察",
            "商机评分": 0,
            "政策摘要": context,
            "国标行业门类名称": "待复核",
            "国标行业门类代码": "待复核",
            "国标行业大类名称": "待复核",
            "国标行业大类代码": "待复核",
            "复核原因": (f"AI 分析失败，需人工复核（{type(error).__name__}: {error_detail}）"),
        }
    )
    return ExportRow("政策观察", values)


def _source_priority(document: PolicyDocument) -> int:
    publisher = normalize_text(document.publisher or "")
    source_name = normalize_text(document.source_name)
    if publisher and (publisher in source_name or source_name in publisher):
        return 0
    if "人民政府" in source_name or "政府政策" in source_name:
        return 1
    return 2


def _deduplicate_documents(
    documents: list[PolicyDocument],
) -> tuple[list[tuple[PolicyDocument, str]], int]:
    grouped: dict[str, list[tuple[int, PolicyDocument]]] = {}
    for index, document in enumerate(documents):
        grouped.setdefault(cross_source_key(document), []).append((index, document))

    selected: list[tuple[PolicyDocument, str]] = []
    duplicate_count = 0
    for identity, group in grouped.items():
        duplicate_count += len(group) - 1
        _, primary = min(group, key=lambda item: (_source_priority(item[1]), item[0]))
        supplementary = list(primary.supplementary_urls)
        for _, document in group:
            if document.policy_id != primary.policy_id:
                supplementary.append(document.detail_url)
                supplementary.extend(document.supplementary_urls)
        selected.append(
            (
                primary.model_copy(
                    update={
                        "supplementary_urls": list(dict.fromkeys(supplementary)),
                    }
                ),
                identity,
            )
        )
    return selected, duplicate_count


def run_pipeline(
    config: RunConfig,
    sources: dict[str, PolicySource],
    retriever: DocumentRetriever,
    analyzer: Analyzer,
    valid_codes: Mapping[str, str] | set[str],
    business_tags: list[str],
) -> tuple[Path, Path]:
    """Collect, analyze, quality-gate, and export one manually configured run."""
    run_started_at = perf_counter()
    report = RunReport(compliance_audit=config.compliance_audit)
    rows: list[ExportRow] = []
    fetched_documents: list[PolicyDocument] = []
    store = StateStore(config.state_path)
    LOGGER.info(
        "任务开始 start_date=%s end_date=%s sources=%s force_reanalyze=%s "
        "output_dir=%s state_path=%s",
        config.start_date,
        config.end_date,
        ",".join(config.source_ids),
        config.force_reanalyze,
        config.output_dir,
        config.state_path,
    )

    try:
        for source_id in config.source_ids:
            LOGGER.info("开始发现政策 source_id=%s", source_id)
            try:
                source = sources[source_id]
                candidates = source.discover(config.start_date, config.end_date)
            except Exception:
                report = _increment(report, "source_failures")
                LOGGER.exception("信源发现失败 source_id=%s", source_id)
                continue

            report = _increment(report, "discovered", len(candidates))
            LOGGER.info("政策发现完成 source_id=%s candidates=%d", source_id, len(candidates))
            for candidate_index, candidate in enumerate(candidates, start=1):
                try:
                    document = retriever.fetch_document(
                        source,
                        candidate,
                        datetime.now(UTC),
                        config.raw_dir,
                    )
                except PermissionError:
                    report = _increment(report, "source_failures")
                    LOGGER.exception(
                        "政策抓取权限失败 source_id=%s candidate=%d/%d",
                        source_id,
                        candidate_index,
                        len(candidates),
                    )
                    break
                except Exception:
                    report = _increment(report, "parse_failures")
                    LOGGER.exception(
                        "政策抓取或解析失败 source_id=%s candidate=%d/%d",
                        source_id,
                        candidate_index,
                        len(candidates),
                    )
                    continue

                if (
                    document.publish_date is not None
                    and not config.start_date <= document.publish_date <= config.end_date
                ):
                    LOGGER.info(
                        "政策超出日期范围，跳过 policy_id=%s publish_date=%s title=%r",
                        document.policy_id,
                        document.publish_date,
                        document.title,
                    )
                    continue
                fetched_documents.append(document)
                LOGGER.info(
                    "政策读取成功 source_id=%s candidate=%d/%d policy_id=%s "
                    "title=%r text_chars=%d",
                    source_id,
                    candidate_index,
                    len(candidates),
                    document.policy_id,
                    document.title,
                    len(document.normalized_text),
                )

        selected_documents, duplicate_count = _deduplicate_documents(fetched_documents)
        report = _increment(report, "skipped", duplicate_count)
        LOGGER.info(
            "政策准备完成 fetched=%d selected=%d duplicates=%d",
            len(fetched_documents),
            len(selected_documents),
            duplicate_count,
        )
        for document_index, (document, dedupe_key) in enumerate(selected_documents, start=1):
            if (
                not config.force_reanalyze
                and not store.is_changed(document.policy_id, document.content_hash, dedupe_key)
            ):
                report = _increment(report, "skipped")
                LOGGER.info(
                    "政策内容未变化，跳过分析 policy=%d/%d policy_id=%s title=%r",
                    document_index,
                    len(selected_documents),
                    document.policy_id,
                    document.title,
                )
                continue
            report = _increment(report, "changed")
            analysis_started_at = perf_counter()
            LOGGER.info(
                "开始分析政策 policy=%d/%d policy_id=%s title=%r",
                document_index,
                len(selected_documents),
                document.policy_id,
                document.title,
            )
            try:
                analysis = analyzer.analyze(document, valid_codes, business_tags)
                analyzed_at = datetime.now(UTC)
                if analysis.is_benefit_policy and not analysis.opportunities:
                    rows.append(_benefit_observation_row(document, analysis, analyzed_at))
                for opportunity in analysis.opportunities:
                    quality = evaluate(
                        document,
                        opportunity,
                        reference_date=config.end_date,
                    )
                    rows.append(
                        _opportunity_row(
                            document,
                            analysis,
                            opportunity,
                            quality,
                            analyzed_at,
                        )
                    )
            except Exception as error:
                report = _increment(report, "analysis_failures")
                LOGGER.exception(
                    "政策分析失败 policy=%d/%d policy_id=%s title=%r "
                    "elapsed_seconds=%.2f",
                    document_index,
                    len(selected_documents),
                    document.policy_id,
                    document.title,
                    perf_counter() - analysis_started_at,
                )
                rows.append(
                    _analysis_failure_observation_row(
                        document,
                        error,
                        datetime.now(UTC),
                    )
                )
                # 401/403 是认证/授权问题，继续跑剩余文章只会全部失败，立即终止整批
                if isinstance(error, httpx.HTTPStatusError) and error.response.status_code in (401, 403):
                    LOGGER.error(
                        "API 认证失败（%d），终止本批分析。请检查 API Key 是否有效。",
                        error.response.status_code,
                    )
                    break
                continue

            store.record_success(document.policy_id, document.content_hash, dedupe_key)
            LOGGER.info(
                "政策分析完成 policy=%d/%d policy_id=%s benefit=%s "
                "opportunities=%d elapsed_seconds=%.2f",
                document_index,
                len(selected_documents),
                document.policy_id,
                analysis.is_benefit_policy,
                len(analysis.opportunities),
                perf_counter() - analysis_started_at,
            )
    finally:
        store.connection.close()

    priority_rows = sum(row.sheet_name == "重点商机" for row in rows)
    report = replace(
        report,
        priority_rows=priority_rows,
        observation_rows=len(rows) - priority_rows,
    )
    workbook_path = export_workbook(rows, config.output_dir, config.end_date)
    report_path = write_report(report, config.output_dir, config.end_date)
    LOGGER.info(
        "任务完成 discovered=%d changed=%d skipped=%d source_failures=%d "
        "parse_failures=%d analysis_failures=%d priority_rows=%d observation_rows=%d "
        "elapsed_seconds=%.2f workbook=%s report=%s",
        report.discovered,
        report.changed,
        report.skipped,
        report.source_failures,
        report.parse_failures,
        report.analysis_failures,
        report.priority_rows,
        report.observation_rows,
        perf_counter() - run_started_at,
        workbook_path,
        report_path,
    )
    return workbook_path, report_path
