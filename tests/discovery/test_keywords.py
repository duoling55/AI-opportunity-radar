import pytest

from opportunity_radar.discovery.keywords import FallbackKeywordSource


def test_fallback_returns_nonempty_keywords():
    src = FallbackKeywordSource(path="config/discovery_keywords.json")
    kws = src.get_search_keywords()
    assert len(kws) > 0
    assert all(k.text and k.tag for k in kws)
    texts = [k.text for k in kws]
    assert "设备更新" in texts and "融资租赁" in texts


def test_fallback_missing_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        FallbackKeywordSource(path=str(tmp_path / "nope.json")).get_search_keywords()
