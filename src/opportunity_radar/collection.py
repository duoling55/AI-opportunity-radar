from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Protocol

from opportunity_radar.compliance import ComplianceAuditSnapshot
from opportunity_radar.config import RunConfig
from opportunity_radar.models import PolicyCandidate, PolicyDocument
from opportunity_radar.parsing.html import DocumentRetriever
from opportunity_radar.pipeline import _deduplicate_documents
from opportunity_radar.sources.base import PolicySource
from opportunity_radar.state import StateStore

LOGGER = logging.getLogger(__name__)


def filter_collectable(
    sources: list[dict],
    compliance_path: str = "config/compliance_sources.json",
) -> list[dict]:
    """FR-02 采集门控：discovery 信源须 phase=verified AND enabled=true 才可采集。

    手动信源（manual）或不在合规台账中的信源不受此门控约束，保持原有行为。
    """
    compliance: dict[str, dict] = {}
    path = Path(compliance_path)
    if path.exists():
        text = path.read_text(encoding="utf-8").strip()
        if text:
            compliance = {record["source_id"]: record for record in json.loads(text)}
    selectable: list[dict] = []
    for source in sources:
        record = compliance.get(source.get("source_id"))
        if (
            record is not None
            and record.get("origin") == "discovery"
            and not (record.get("phase") == "verified" and record.get("enabled"))
        ):
            continue
        selectable.append(source)
    return selectable


@dataclass(frozen=True)
class CollectionReport:
    discovered: int = 0
    collected: int = 0
    skipped: int = 0
    source_failures: int = 0
    parse_failures: int = 0


@dataclass(frozen=True)
class PolicyBatch:
    start_date: date
    end_date: date
    source_ids: tuple[str, ...]
    compliance_audit: tuple[ComplianceAuditSnapshot, ...]
    documents: tuple[PolicyDocument, ...]
    report: CollectionReport
    development_mode: bool = False


class BrowserFallback(Protocol):
    def discover(
        self,
        source: PolicySource,
        start: date,
        end: date,
    ) -> list[PolicyCandidate]: ...

    def fetch_document(
        self,
        source: PolicySource,
        candidate: PolicyCandidate,
        collected_at: datetime,
        raw_dir: Path,
    ) -> PolicyDocument: ...

    def close(self) -> None: ...


def _increment(report: CollectionReport, field: str, amount: int = 1) -> CollectionReport:
    values = asdict(report)
    values[field] += amount
    return CollectionReport(**values)


def _available_batch_path(directory: Path, end_date: date) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"policy-batch-{end_date.isoformat()}.json"
    sequence = 1
    while path.exists():
        path = directory / f"policy-batch-{end_date.isoformat()}-{sequence}.json"
        sequence += 1
    return path


def write_batch(batch: PolicyBatch, directory: Path) -> Path:
    path = _available_batch_path(directory, batch.end_date)
    payload = {
        "schema_version": 1,
        "created_at": datetime.now(UTC).isoformat(),
        "start_date": batch.start_date.isoformat(),
        "end_date": batch.end_date.isoformat(),
        "source_ids": list(batch.source_ids),
        "development_mode": batch.development_mode,
        "compliance_audit": [
            {
                **asdict(item),
                "verified_at": item.verified_at.isoformat(),
            }
            for item in batch.compliance_audit
        ],
        "report": asdict(batch.report),
        "documents": [
            document.model_dump(mode="json")
            for document in batch.documents
        ],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def load_batch(path: Path) -> PolicyBatch:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != 1:
        raise ValueError("unsupported policy batch schema")
    return PolicyBatch(
        start_date=date.fromisoformat(payload["start_date"]),
        end_date=date.fromisoformat(payload["end_date"]),
        source_ids=tuple(payload["source_ids"]),
        compliance_audit=tuple(
            ComplianceAuditSnapshot(
                source_id=item["source_id"],
                verified_at=date.fromisoformat(item["verified_at"]),
                evidence_url=item["evidence_url"],
                adapter_version=item["adapter_version"],
            )
            for item in payload["compliance_audit"]
        ),
        documents=tuple(
            PolicyDocument.model_validate(item)
            for item in payload["documents"]
        ),
        report=CollectionReport(**payload["report"]),
        development_mode=payload.get("development_mode", False),
    )


def latest_batch(directory: Path) -> Path:
    candidates = sorted(
        directory.glob("policy-batch-*.json"),
        key=lambda item: item.stat().st_mtime,
    )
    if not candidates:
        raise ValueError(f"no policy batch found in {directory}")
    return candidates[-1]


def collect_batch(
    config: RunConfig,
    sources: dict[str, PolicySource],
    retriever: DocumentRetriever,
    *,
    browser: BrowserFallback | None = None,
    browser_mode: str = "fallback",
    development_mode: bool = False,
) -> Path:
    """Collect official documents into an immutable local batch without using an LLM."""
    report = CollectionReport()
    fetched: list[PolicyDocument] = []
    collection_state = StateStore(config.state_path.parent / "collection.sqlite3")
    try:
        for source_id in config.source_ids:
            source = sources[source_id]
            prefer_direct_http = bool(getattr(source, "prefer_direct_http", False))
            LOGGER.info(
                "信源发现开始 source_id=%s browser_mode=%s start_date=%s end_date=%s",
                source_id,
                browser_mode,
                config.start_date,
                config.end_date,
            )
            try:
                if browser is not None and browser_mode == "always" and not prefer_direct_http:
                    candidates = browser.discover(source, config.start_date, config.end_date)
                else:
                    try:
                        candidates = source.discover(config.start_date, config.end_date)
                    except PermissionError:
                        raise
                    except Exception:
                        if browser is None:
                            raise
                        candidates = browser.discover(
                            source,
                            config.start_date,
                            config.end_date,
                        )
                    else:
                        if not candidates and browser is not None:
                            candidates = browser.discover(
                                source,
                                config.start_date,
                                config.end_date,
                            )
            except Exception:
                LOGGER.exception(
                    "信源发现失败 source_id=%s browser_mode=%s",
                    source_id,
                    browser_mode,
                )
                report = _increment(report, "source_failures")
                continue

            if candidates:
                LOGGER.info(
                    "信源发现完成 source_id=%s candidates=%d",
                    source_id,
                    len(candidates),
                )
            else:
                LOGGER.warning(
                    "信源未发现候选 source_id=%s browser_mode=%s "
                    "start_date=%s end_date=%s；请检查列表地址、页面选择器和日期范围",
                    source_id,
                    browser_mode,
                    config.start_date,
                    config.end_date,
                )
            report = _increment(report, "discovered", len(candidates))
            for candidate in candidates:
                try:
                    if browser is not None and browser_mode == "always" and not prefer_direct_http:
                        document = browser.fetch_document(
                            source,
                            candidate,
                            datetime.now(UTC),
                            config.raw_dir,
                        )
                    else:
                        try:
                            document = retriever.fetch_document(
                                source,
                                candidate,
                                datetime.now(UTC),
                                config.raw_dir,
                            )
                        except PermissionError:
                            raise
                        except Exception:
                            if browser is None:
                                raise
                            document = browser.fetch_document(
                                source,
                                candidate,
                                datetime.now(UTC),
                                config.raw_dir,
                            )
                except PermissionError:
                    LOGGER.exception(
                        "信源访问受限 source_id=%s title=%r url=%s",
                        source_id,
                        candidate.title,
                        candidate.detail_url,
                    )
                    report = _increment(report, "source_failures")
                    break
                except Exception:
                    LOGGER.exception(
                        "公文解析失败 source_id=%s title=%r url=%s",
                        source_id,
                        candidate.title,
                        candidate.detail_url,
                    )
                    report = _increment(report, "parse_failures")
                    continue

                if (
                    document.publish_date is not None
                    and not config.start_date <= document.publish_date <= config.end_date
                ):
                    continue
                fetched.append(document)

        selected, duplicate_count = _deduplicate_documents(fetched)
        report = _increment(report, "skipped", duplicate_count)
        changed: list[PolicyDocument] = []
        changed_keys: list[str] = []
        for document, dedupe_key in selected:
            if collection_state.is_changed(
                document.policy_id,
                document.content_hash,
                dedupe_key,
            ):
                changed.append(document)
                changed_keys.append(dedupe_key)
            else:
                report = _increment(report, "skipped")
        report = _increment(report, "collected", len(changed))
        batch = PolicyBatch(
            config.start_date,
            config.end_date,
            config.source_ids,
            config.compliance_audit,
            tuple(changed),
            report,
            development_mode,
        )
        path = write_batch(batch, config.normalized_dir / "batches")
        for document, dedupe_key in zip(changed, changed_keys, strict=True):
            collection_state.record_success(
                document.policy_id,
                document.content_hash,
                dedupe_key,
            )
        return path
    finally:
        collection_state.connection.close()
        if browser is not None:
            browser.close()


class LocalPolicySource:
    def __init__(self, documents: tuple[PolicyDocument, ...]) -> None:
        self.documents = documents

    def discover(self, start: date, end: date) -> list[PolicyCandidate]:
        return [
            PolicyCandidate(
                source_id=document.source_id,
                title=document.title,
                detail_url=document.detail_url,
                published_at=document.publish_date,
            )
            for document in self.documents
            if document.publish_date is None or start <= document.publish_date <= end
        ]


class LocalDocumentRetriever:
    def __init__(self, documents: tuple[PolicyDocument, ...]) -> None:
        self.documents = {
            (document.source_id, str(document.detail_url)): document
            for document in documents
        }

    def fetch_document(
        self,
        source: LocalPolicySource,
        candidate: PolicyCandidate,
        collected_at: datetime,
        raw_dir: Path,
    ) -> PolicyDocument:
        del source, collected_at, raw_dir
        return self.documents[(candidate.source_id, str(candidate.detail_url))]


def local_sources(
    batch: PolicyBatch,
) -> tuple[dict[str, LocalPolicySource], LocalDocumentRetriever]:
    by_source: dict[str, list[PolicyDocument]] = {}
    for document in batch.documents:
        by_source.setdefault(document.source_id, []).append(document)
    sources = {
        source_id: LocalPolicySource(tuple(documents))
        for source_id, documents in by_source.items()
    }
    return sources, LocalDocumentRetriever(batch.documents)
