import json
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path

from opportunity_radar.compliance import ComplianceAuditSnapshot


@dataclass(frozen=True)
class RunReport:
    """Machine-readable counts for one policy opportunity collection run."""

    discovered: int = 0
    changed: int = 0
    skipped: int = 0
    source_failures: int = 0
    parse_failures: int = 0
    analysis_failures: int = 0
    priority_rows: int = 0
    observation_rows: int = 0
    compliance_audit: tuple[ComplianceAuditSnapshot, ...] = ()


def write_report(report: RunReport, output_dir: Path, run_date: date) -> Path:
    """Write the run counts as UTF-8 JSON for downstream automation."""
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"policy-opportunities-{run_date.isoformat()}-report.json"
    sequence = 1
    while path.exists():
        path = output_dir / (
            f"policy-opportunities-{run_date.isoformat()}-report-{sequence}.json"
        )
        sequence += 1
    payload = asdict(report)
    for snapshot in payload["compliance_audit"]:
        snapshot["verified_at"] = snapshot["verified_at"].isoformat()
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return path
