import json
from datetime import date
from pathlib import Path

from opportunity_radar.compliance import ComplianceAuditSnapshot
from opportunity_radar.export.report import RunReport, write_report


def test_write_report_records_discovery_change_failure_and_row_counts(tmp_path: Path) -> None:
    report = RunReport(
        discovered=4,
        changed=2,
        skipped=1,
        source_failures=1,
        parse_failures=2,
        analysis_failures=3,
        priority_rows=5,
        observation_rows=6,
        compliance_audit=(
            ComplianceAuditSnapshot(
                source_id="verified",
                verified_at=date(2026, 7, 1),
                evidence_url="https://example.gov.cn/permission",
                adapter_version="1.2.3",
            ),
        ),
    )

    path = write_report(report, tmp_path, date(2026, 7, 29))

    assert path.name == "policy-opportunities-2026-07-29-report.json"
    assert json.loads(path.read_text(encoding="utf-8")) == {
        "discovered": 4,
        "changed": 2,
        "skipped": 1,
        "source_failures": 1,
        "parse_failures": 2,
        "analysis_failures": 3,
        "priority_rows": 5,
        "observation_rows": 6,
        "compliance_audit": [
            {
                "source_id": "verified",
                "verified_at": "2026-07-01",
                "evidence_url": "https://example.gov.cn/permission",
                "adapter_version": "1.2.3",
            }
        ],
    }


def test_write_report_preserves_existing_report_with_collision_suffix(
    tmp_path: Path,
) -> None:
    first = write_report(RunReport(discovered=1), tmp_path, date(2026, 7, 29))
    second = write_report(RunReport(discovered=2), tmp_path, date(2026, 7, 29))

    assert first.name == "policy-opportunities-2026-07-29-report.json"
    assert second.name == "policy-opportunities-2026-07-29-report-1.json"
    assert json.loads(first.read_text(encoding="utf-8"))["discovered"] == 1
    assert json.loads(second.read_text(encoding="utf-8"))["discovered"] == 2
