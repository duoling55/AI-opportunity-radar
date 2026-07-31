from __future__ import annotations

import json
from pathlib import Path


def load_industry_codes(path: Path) -> dict[str, str]:
    """Load the canonical local GB/T code-to-name table."""
    return {
        item["code"]: item["name"]
        for item in json.loads(path.read_text(encoding="utf-8"))
    }
