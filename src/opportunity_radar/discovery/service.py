from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse


class DiscoveryService:
    """发现信源的服务层：候选列表、人工审核、提升为正式信源。

    compliance_sources.json 为 discovery 信源唯一真源；promote 时双写 sources.json
    使 01 信源编辑可见可采集。候选由 DiscoveryOrchestrator 写入（origin=discovery）。
    """

    def __init__(
        self,
        compliance_path: str = "config/compliance_sources.json",
        sources_path: str = "config/sources.json",
    ) -> None:
        self._comp = Path(compliance_path)
        self._src = Path(sources_path)

    # -- 读 --

    def list_candidates(self) -> list[dict]:
        """返回 origin=discovery 的候选，按 source_id 去重保留最新一条。"""
        latest: dict[str, dict] = {}
        for record in self._read(self._comp):
            if record.get("origin") == "discovery":
                latest[record["source_id"]] = record
        return list(latest.values())

    def get_candidate(self, source_id: str) -> dict | None:
        for record in self._read(self._comp):
            if (
                record["source_id"] == source_id
                and record.get("origin") == "discovery"
            ):
                return record
        return None

    # -- 写 --

    def promote(
        self,
        source_id: str,
        reviewer: str,
        override_not_recommended: bool = False,
    ) -> dict:
        recs = self._read(self._comp)
        rec = self._find(recs, source_id)
        if rec.get("origin") != "discovery" or rec.get("phase") != "candidate":
            raise ValueError(f"无法提升：{source_id} 非候选信源")
        check = rec.get("discovery", {}).get("check_result")
        if check == "not_recommended" and not override_not_recommended:
            raise ValueError("not_recommended 信源需 override_not_recommended=True 二次确认")
        rec["phase"] = "verified"
        rec["enabled"] = True
        rec["verified_at"] = str(datetime.now(UTC).date())
        rec["owner"] = reviewer
        if override_not_recommended and check == "not_recommended":
            rec.setdefault("verification_notes", "")
            rec["verification_notes"] = "override not_recommended; " + rec["verification_notes"]
        self._write(self._comp, recs)
        self._sync_sources(rec)
        return rec

    def review(
        self,
        source_id: str,
        action: str,
        reason: str | None,
        reviewer: str,
        comment: str = "",
    ) -> dict:
        if action == "confirm":
            return self.promote(source_id, reviewer=reviewer)
        recs = self._read(self._comp)
        rec = self._find(recs, source_id)
        rec.setdefault("verification_notes", "")
        if action == "reject":
            if not reason:
                raise ValueError("驳回必填原因")
            rec["phase"] = "retired"
            rec["enabled"] = False
            rec["verification_notes"] = f"驳回:{reason}; {comment}"
        elif action == "watch":
            rec["verification_notes"] += f"关注:{comment};"
        else:
            raise ValueError(f"未知动作: {action}")
        rec["reviewer"] = reviewer
        rec["reviewed_at"] = datetime.now(UTC).isoformat()
        self._write(self._comp, recs)
        return rec

    # -- 内部 --

    def _sync_sources(self, rec: dict) -> None:
        srcs = self._read(self._src)
        srcs = [s for s in srcs if s.get("source_id") != rec["source_id"]]
        srcs.append(
            {
                "source_id": rec["source_id"],
                "display_name": rec["display_name"],
                "region": rec["region"],
                "list_urls": list(rec.get("official_urls", [])),
                "allowed_domains": self._domains(rec),
                "request_interval_seconds": 1.5,
                "adapter_version": "generic",
                "origin": "discovery",
                "enabled": True,
            }
        )
        self._write(self._src, srcs)

    @staticmethod
    def _domains(rec: dict) -> list[str]:
        out: list[str] = []
        for url in rec.get("official_urls", []):
            host = urlparse(url).hostname
            if host and host not in out:
                out.append(host)
        return out

    @staticmethod
    def _find(recs: list[dict], source_id: str) -> dict:
        for record in recs:
            if record["source_id"] == source_id:
                return record
        raise ValueError(f"未找到信源: {source_id}")

    @staticmethod
    def _read(path: Path) -> list:
        if not path.exists():
            return []
        text = path.read_text(encoding="utf-8").strip()
        return json.loads(text) if text else []

    @staticmethod
    def _write(path: Path, data: list) -> None:
        path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
