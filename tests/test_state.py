from datetime import UTC, date, datetime
from pathlib import Path

from opportunity_radar.models import PolicyCandidate, PolicyDocument
from opportunity_radar.normalization import (
    content_hash,
    cross_source_key,
    make_policy_id,
)
from opportunity_radar.parsing.snapshot import save_snapshot
from opportunity_radar.state import StateStore


def test_state_store_skips_unchanged_and_accepts_updated_content(tmp_path: Path) -> None:
    candidate = PolicyCandidate(
        source_id="miit",
        title="设备更新通知",
        detail_url="https://www.miit.gov.cn/art/1.html",
    )
    policy_id = make_policy_id(candidate)
    first_hash = content_hash("正文一")
    store = StateStore(tmp_path / "state.sqlite3")

    assert store.is_changed(policy_id, first_hash) is True
    store.record_success(policy_id, first_hash)
    assert store.is_changed(policy_id, first_hash) is False
    assert store.is_changed(policy_id, content_hash("正文二")) is True


def test_content_hash_normalizes_whitespace_and_policy_id_uses_canonical_url() -> None:
    first = PolicyCandidate(
        source_id="miit",
        title="设备更新通知",
        detail_url="HTTPS://WWW.MIIT.GOV.CN/art/1.html/?tracking=1#section",
    )
    second = PolicyCandidate(
        source_id="miit",
        title="更新后的标题",
        detail_url="https://www.miit.gov.cn/art/1.html",
    )

    assert content_hash("正文\n\n一") == content_hash(" 正文 一 ")
    assert make_policy_id(first) == make_policy_id(second)


def test_policy_id_retains_identity_query_parameters() -> None:
    first = PolicyCandidate(
        source_id="zhejiang_huiqi",
        title="政策一",
        detail_url="https://example.gov/detail.html?id=62339&utm_source=test",
    )
    second = PolicyCandidate(
        source_id="zhejiang_huiqi",
        title="政策二",
        detail_url="https://example.gov/detail.html?id=62340&utm_source=test",
    )

    assert make_policy_id(first) != make_policy_id(second)


def test_policy_id_prefers_normalized_document_number_over_url() -> None:
    first = PolicyCandidate(
        source_id="miit",
        title="设备更新通知",
        detail_url="https://www.miit.gov.cn/art/1.html",
    )
    second = PolicyCandidate(
        source_id="miit",
        title="转载标题",
        detail_url="https://www.miit.gov.cn/art/2.html",
    )

    assert make_policy_id(first, "工信部〔2026〕 1 号") == make_policy_id(
        second, "工信部[2026]1号"
    )


def test_save_snapshot_writes_bytes_under_current_utc_date(tmp_path: Path) -> None:
    saved = save_snapshot(tmp_path, "policy-1", "html", b"<p>policy</p>")

    assert saved == tmp_path / datetime.now(UTC).strftime("%Y%m%d") / "policy-1.html"
    assert saved.read_bytes() == b"<p>policy</p>"


def test_save_snapshot_preserves_colliding_content_with_sequence_suffix(
    tmp_path: Path,
) -> None:
    first = save_snapshot(tmp_path, "policy-1", "html", b"first")
    second = save_snapshot(tmp_path, "policy-1", "html", b"second")

    assert first.name == "policy-1.html"
    assert second.name == "policy-1-1.html"
    assert first.read_bytes() == b"first"
    assert second.read_bytes() == b"second"


def test_state_store_deduplicates_cross_source_repost_by_shared_identity(
    tmp_path: Path,
) -> None:
    first = PolicyDocument(
        policy_id="first",
        source_id="government",
        source_name="政府政策库",
        region="江苏",
        title="相同政策",
        detail_url="https://government.example/first",
        document_number="苏政〔2026〕1号",
        publish_date=date(2026, 7, 1),
        raw_text="相同政策正文",
        normalized_text="相同政策正文",
        collected_at=datetime(2026, 7, 2, tzinfo=UTC),
        content_hash=content_hash("相同政策正文"),
        snapshot_path="raw/first.html",
    )
    repost = first.model_copy(
        update={
            "policy_id": "repost",
            "source_id": "issuer",
            "detail_url": "https://issuer.example/repost",
        }
    )
    store = StateStore(tmp_path / "state.sqlite3")
    identity = cross_source_key(first)

    store.record_success(first.policy_id, first.content_hash, identity)

    assert store.is_changed(repost.policy_id, repost.content_hash, identity) is False
