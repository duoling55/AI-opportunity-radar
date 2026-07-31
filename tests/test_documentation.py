from pathlib import Path


def test_readme_states_no_source_is_currently_eligible_and_requires_both_records() -> None:
    readme = Path("README.md").read_text(encoding="utf-8")

    assert "当前没有任何自动来源具备运行资格" in readme
    assert "config/sources.json" in readme
    assert "config/compliance_sources.json" in readme
    if "--sources miit" in readme:
        assert "--dev-unverified-sources" in readme
        assert "只对 `collect` 生效" in readme
    assert "all configured automatic policy sources are selected" not in readme


def test_smoke_check_downgrades_adapter_and_compliance_records_on_restriction() -> None:
    procedure = Path("docs/operations/policy-source-smoke-check.md").read_text(
        encoding="utf-8"
    )

    assert "`config/sources.json` 中将 `enabled` 设为 `false`" in procedure
    assert "`config/compliance_sources.json`" in procedure
    assert "`phase=candidate`" in procedure
    assert "`enabled=false`" in procedure
    assert "`verified_at=null`" in procedure
    assert "`review_due_at` 设置为未来复核日期" in procedure
    assert "`verification_notes` 记录限制原因" in procedure
