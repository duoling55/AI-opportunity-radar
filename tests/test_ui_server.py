from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from openpyxl import Workbook

from opportunity_radar import ui_server
from opportunity_radar.collection import load_batch
from opportunity_radar.models import PolicyDocument


def test_ui_source_validation_accepts_zero_development_interval() -> None:
    sources = ui_server._source_payload()
    sources[0]["request_interval_seconds"] = 0

    payload = ui_server._validate_sources(sources)

    assert payload[0]["request_interval_seconds"] == 0


def test_ui_source_validation_rejects_url_outside_allowed_domains() -> None:
    sources = ui_server._source_payload()
    sources[0]["list_urls"] = ["https://attacker.example/list"]

    with pytest.raises(ValueError, match="网址域名未列入允许域名"):
        ui_server._validate_sources(sources)


def test_ui_reads_existing_workbook_as_structured_rows(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "重点商机"
    sheet.append(["政策名称", "商机评分"])
    sheet.append(["设备更新通知", 88])
    path = tmp_path / "policy-opportunities-2026-07-31.xlsx"
    workbook.save(path)
    monkeypatch.setattr(ui_server, "OUTPUT_DIRECTORY", tmp_path)

    payload = ui_server._workbook_payload(path.name)

    assert payload["selected_sheet"] == "重点商机"
    assert payload["rows"] == [{"政策名称": "设备更新通知", "商机评分": 88}]


def test_ui_saves_and_reloads_prompt_defaults(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    prompt_path = tmp_path / "analysis_prompts.json"
    monkeypatch.setattr(ui_server, "PROMPT_CONFIG_PATH", prompt_path)
    current = ui_server._prompt_payload()
    custom_system = "你是自定义政策分析员，只依据正文。"
    custom_template = "自定义分析要求\n" + str(current["user_prompt_template"])

    saved = ui_server._save_prompts(
        {
            "system_prompt": custom_system,
            "user_prompt_template": custom_template,
        }
    )

    assert saved["system_prompt"] == custom_system
    assert saved["user_prompt_template"] == custom_template
    assert ui_server._prompt_payload()["system_prompt"] == custom_system


def test_ui_analysis_passes_page_prompts_to_model_process(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    batch_path = tmp_path / "policy-batch-2026-07-31.json"
    batch_path.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(ui_server, "BATCH_DIRECTORY", tmp_path)
    captured: dict[str, object] = {}

    class _RunningProcess:
        def poll(self) -> None:
            return None

    def fake_start_job(
        label: str,
        arguments: list[str],
        environment: dict[str, str],
    ) -> ui_server.UiJob:
        captured.update(
            {
                "label": label,
                "arguments": arguments,
                "environment": environment,
            }
        )
        return ui_server.UiJob(
            "job-1",
            label,
            _RunningProcess(),  # type: ignore[arg-type]
            tmp_path / "missing.log",
            datetime(2026, 7, 31, tzinfo=UTC),
        )

    monkeypatch.setattr(ui_server, "_start_job", fake_start_job)
    prompts = ui_server._prompt_payload()
    custom_template = "页面自定义要求\n" + str(prompts["user_prompt_template"])

    ui_server._start_analysis(
        {
            "batch_name": batch_path.name,
            "provider": "openai",
            "base_url": "https://ai.example/v1",
            "model": "test-model",
            "api_key": "runtime-key",
            "system_prompt": "页面系统提示词",
            "user_prompt_template": custom_template,
            "force": True,
        }
    )

    environment = captured["environment"]
    assert isinstance(environment, dict)
    assert environment["OPPORTUNITY_RADAR_SYSTEM_PROMPT"] == "页面系统提示词"
    assert environment["OPPORTUNITY_RADAR_USER_PROMPT_TEMPLATE"] == custom_template
    assert captured["arguments"][-1] == "--force"


def test_ui_creates_analysis_batch_with_only_selected_policies(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    batch_directory = tmp_path / "batches"
    job_directory = tmp_path / "jobs"
    batch_directory.mkdir()
    documents = [
        PolicyDocument(
            policy_id=f"policy-{index}",
            source_id="fixture",
            source_name="测试信源",
            region="浙江",
            title=f"政策 {index}",
            detail_url=f"https://example.gov.cn/policy/{index}",
            raw_text=f"政策正文 {index}",
            normalized_text=f"政策正文 {index}",
            collected_at=datetime(2026, 7, 31, tzinfo=UTC),
            content_hash=f"hash-{index}",
            snapshot_path=f"data/raw/policy-{index}.html",
        )
        for index in range(1, 4)
    ]
    source_batch = batch_directory / "policy-batch-2026-07-31.json"
    source_batch.write_text(
        ui_server.json.dumps(
            {
                "schema_version": 1,
                "created_at": "2026-07-31T00:00:00+00:00",
                "start_date": "2026-07-01",
                "end_date": "2026-07-31",
                "source_ids": ["fixture"],
                "development_mode": True,
                "compliance_audit": [],
                "report": {
                    "discovered": 3,
                    "collected": 3,
                    "skipped": 0,
                    "source_failures": 0,
                    "parse_failures": 0,
                },
                "documents": [
                    document.model_dump(mode="json") for document in documents
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(ui_server, "BATCH_DIRECTORY", batch_directory)
    monkeypatch.setattr(ui_server, "JOB_DIRECTORY", job_directory)

    selection_path, count = ui_server._selection_batch_path(
        source_batch.name,
        ["policy-1", "policy-3"],
    )

    selection = load_batch(selection_path)
    assert count == 2
    assert [document.policy_id for document in selection.documents] == [
        "policy-1",
        "policy-3",
    ]


def test_ui_marks_completed_job_with_analysis_failures_as_warning(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    output_directory = tmp_path / "outputs"
    output_directory.mkdir()
    report_path = output_directory / "policy-opportunities-2026-07-31-report.json"
    report_path.write_text(
        ui_server.json.dumps(
            {
                "changed": 1,
                "analysis_failures": 1,
                "priority_rows": 0,
                "observation_rows": 1,
            }
        ),
        encoding="utf-8",
    )
    log_path = tmp_path / "job.log"
    log_path.write_text(f"Report: {report_path}\n", encoding="utf-8")
    monkeypatch.setattr(ui_server, "OUTPUT_DIRECTORY", output_directory)

    class _CompletedProcess:
        def poll(self) -> int:
            return 0

    job = ui_server.UiJob(
        "job-1",
        "分析测试批次",
        _CompletedProcess(),  # type: ignore[arg-type]
        log_path,
        datetime(2026, 7, 31, tzinfo=UTC),
    )

    payload = ui_server._job_payload(job)

    assert payload["status"] == "warning"
    assert payload["report"] == {
        "changed": 1,
        "analysis_failures": 1,
        "priority_rows": 0,
        "observation_rows": 1,
    }
