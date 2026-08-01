from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from opportunity_radar.compliance import ComplianceAuditSnapshot


@dataclass(frozen=True)
class SourceConfig:
    source_id: str
    display_name: str
    region: str
    list_urls: tuple[str, ...]
    allowed_domains: tuple[str, ...]
    enabled: bool = True
    request_interval_seconds: float = 1.0
    adapter_version: str = "unregistered"
    origin: str = "manual"  # manual | discovery

    def __post_init__(self) -> None:
        if type(self.enabled) is not bool:
            raise ValueError("enabled must be a JSON boolean")
        if not isinstance(self.adapter_version, str) or not self.adapter_version.strip():
            raise ValueError("adapter_version must be a nonempty string")


@dataclass(frozen=True)
class RunConfig:
    start_date: date
    end_date: date
    source_ids: tuple[str, ...]
    output_dir: Path = Path("outputs")
    state_path: Path = Path("data/state/radar.sqlite3")
    raw_dir: Path = Path("data/raw")
    normalized_dir: Path = Path("data/normalized")
    compliance_audit: tuple[ComplianceAuditSnapshot, ...] = ()
    force_reanalyze: bool = False

    @classmethod
    def from_optional_dates(
        cls,
        start_date: date | None,
        end_date: date | None,
        source_ids: tuple[str, ...],
        compliance_audit: tuple[ComplianceAuditSnapshot, ...] = (),
    ) -> RunConfig:
        resolved_end = end_date or datetime.now(UTC).date()
        resolved_start = start_date or resolved_end - timedelta(days=30)
        if resolved_start > resolved_end:
            raise ValueError("start_date must not be later than end_date")
        return cls(
            resolved_start,
            resolved_end,
            source_ids,
            compliance_audit=compliance_audit,
        )


def load_sources(path: Path) -> dict[str, SourceConfig]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    sources: dict[str, SourceConfig] = {}
    for item in payload:
        enabled = item.get("enabled", True)
        if type(enabled) is not bool:
            raise ValueError(
                f"source {item.get('source_id', '<missing>')}: "
                "enabled must be a JSON boolean"
            )
        source = SourceConfig(
            source_id=item["source_id"],
            display_name=item["display_name"],
            region=item["region"],
            list_urls=tuple(item["list_urls"]),
            allowed_domains=tuple(item["allowed_domains"]),
            enabled=enabled,
            request_interval_seconds=float(item.get("request_interval_seconds", 1.0)),
            adapter_version=item.get("adapter_version", "unregistered"),
            origin=item.get("origin", "manual"),
        )
        if source.source_id in sources:
            raise ValueError(f"duplicate source_id: {source.source_id}")
        sources[source.source_id] = source
    return sources
