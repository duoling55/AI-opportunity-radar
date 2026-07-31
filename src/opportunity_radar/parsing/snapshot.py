from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path


def save_snapshot(root: Path, policy_id: str, suffix: str, body: bytes) -> Path:
    """Save raw source bytes under the collection date for reproducible processing."""
    directory = root / datetime.now(UTC).strftime("%Y%m%d")
    directory.mkdir(parents=True, exist_ok=True)
    destination = directory / f"{policy_id}.{suffix}"
    sequence = 1
    while destination.exists():
        destination = directory / f"{policy_id}-{sequence}.{suffix}"
        sequence += 1
    destination.write_bytes(body)
    return destination
