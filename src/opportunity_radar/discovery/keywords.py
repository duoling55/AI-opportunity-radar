from __future__ import annotations

import json
from pathlib import Path
from typing import Protocol

from opportunity_radar.discovery.models import SearchKeyword


class KeywordSource(Protocol):
    def get_search_keywords(self) -> list[SearchKeyword]: ...


class FallbackKeywordSource:
    """读取 config/discovery_keywords.json；FR-05 落地前替代 KbKeywordSource。"""

    def __init__(self, path: str = "config/discovery_keywords.json") -> None:
        self._path = Path(path)

    def get_search_keywords(self) -> list[SearchKeyword]:
        if not self._path.exists():
            raise FileNotFoundError(f"关键词文件不存在: {self._path}")
        raw = json.loads(self._path.read_text(encoding="utf-8"))
        return [
            SearchKeyword(text=k["text"], tag=k["tag"], signal_strength=k.get("signal_strength"))
            for k in raw
        ]
