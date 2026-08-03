from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path

from opportunity_radar.discovery.models import (
    ComplianceReport,
    CrawlResult,
    DiscoveryMeta,
    DiscoveryReport,
    SamplePolicy,
    ScoreResult,
)


def load_portal_seeds(path: str = "config/discovery_portals.json") -> list[dict]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


class DiscoveryOrchestrator:
    """Spec 1 编排器：集成爬取 -> 合规核查 -> 评分，产出候选信源与发现报告。

    单门户失败或受限不中断整批；候选写入 compliance_sources.json，
    发现报告写入 report_dir。
    """

    def __init__(
        self,
        crawler,
        checker,
        scorer,
        keyword_source,
        compliance_path: str = "config/compliance_sources.json",
        report_dir: str = "data/discovery",
    ) -> None:
        self._crawler = crawler
        self._checker = checker
        self._scorer = scorer
        self._kw = keyword_source
        self._comp_path = Path(compliance_path)
        self._report_dir = Path(report_dir)

    def run(
        self,
        keyword_tags: list[str] | None,
        portal_ids: list[str] | None,
        mode: str = "direct-crawl",
    ) -> DiscoveryReport:
        started = datetime.now(UTC).isoformat()
        job_id = f"disc-{uuid.uuid4().hex[:8]}"
        keywords = self._filter_keywords(keyword_tags)
        portals = self._filter_portals(portal_ids)

        candidates: list[dict] = []
        portals_scanned: list[dict] = []
        errors: list[dict] = []
        restricted = 0

        for p in portals:
            try:
                cr: CrawlResult = self._crawler.crawl(
                    p["entry_url"], p["portal_id"], allowed_domains=(p["gov_domain"],)
                )
            except Exception as e:  # noqa: BLE001 - 单门户失败不中断整批
                errors.append({"portal_id": p["portal_id"], "reason": "exception", "detail": str(e)})
                portals_scanned.append(
                    {"portal_id": p["portal_id"], "url": p["entry_url"], "status": "error", "policies_found": 0}
                )
                continue

            if cr.restricted:
                restricted += 1
                errors.append({"portal_id": p["portal_id"], "reason": cr.restricted_reason, "detail": ""})
                portals_scanned.append(
                    {"portal_id": p["portal_id"], "url": p["entry_url"], "status": "restricted", "policies_found": 0}
                )
                continue

            matched = self._match_keywords(cr, keywords)
            if not matched:
                portals_scanned.append(
                    {"portal_id": p["portal_id"], "url": p["entry_url"], "status": "ok", "policies_found": 0}
                )
                continue

            cand = self._build_candidate(p, cr, matched)
            candidates.append(cand)
            portals_scanned.append(
                {"portal_id": p["portal_id"], "url": p["entry_url"], "status": "ok", "policies_found": len(matched)}
            )

        cand_ids = [c["source_id"] for c in candidates]
        self._write_candidates(candidates)

        report = DiscoveryReport(
            job_id=job_id,
            started_at=started,
            finished_at=datetime.now(UTC).isoformat(),
            keywords_used=[k.text for k in keywords],
            portals_scanned=portals_scanned,
            candidates=cand_ids,
            stats={
                "portals_scanned": len(portals),
                "policies_extracted": sum(s["policies_found"] for s in portals_scanned),
                "candidates_found": len(cand_ids),
                "restricted_stopped": restricted,
            },
            errors=errors,
        )
        self._write_report(report)
        return report

    def _filter_keywords(self, tags):
        kws = self._kw.get_search_keywords()
        if not tags:
            return kws
        return [k for k in kws if k.tag in tags]

    def _filter_portals(self, ids):
        portals = load_portal_seeds()
        if not ids:
            return portals
        return [p for p in portals if p["portal_id"] in ids]

    @staticmethod
    def _match_keywords(cr: CrawlResult, keywords) -> list[dict]:
        """关键词过滤；无关键词时放行全部 policy_items（发现模式）。"""
        matched = []
        for item in cr.policy_items:
            if not keywords:
                matched.append({"title": item.title, "url": item.url, "matched_keywords": []})
            else:
                hit = [k.text for k in keywords if k.text in item.title or k.text in cr.text_content]
                if hit:
                    matched.append(
                        {"title": item.title, "url": item.url, "matched_keywords": list(set(hit))}
                    )
        return matched[:5]

    def _build_candidate(self, portal, cr, matched) -> dict:
        comp: ComplianceReport = self._checker.check(
            {
                "url": cr.final_url,
                "domain": portal["gov_domain"],
                "sample_policies": matched,
                "scan_result": cr,
            }
        )
        score: ScoreResult = self._scorer.score(
            {
                "admin_level": portal["admin_level"],
                "domain": portal["gov_domain"],
                "column_name": cr.page_title,
                "sample_policies": matched,
            },
            matched,
            comp,
        )
        meta = DiscoveryMeta(
            keywords=sorted({k for m in matched for k in m["matched_keywords"]}),
            discovered_at=datetime.now(UTC).date(),
            portal_seed_id=portal["portal_id"],
            admin_level=portal["admin_level"],
            sample_policies=[SamplePolicy(**m) for m in matched],
            snapshots=[cr.snapshot_path] if cr.snapshot_path else [],
            check_result=comp.check_result,
            check_details=comp.check_details,
            recommendation=comp.recommendation,
            priority_score=score.priority_score,
            priority_level=score.priority_level,
            score_breakdown=score.score_breakdown,
        )
        return {
            "source_id": portal["portal_id"],
            "display_name": portal["display_name"],
            "region": portal["region"],
            "phase": "candidate",
            "enabled": False,
            "official_urls": [portal["entry_url"]],
            "origin": "discovery",
            "discovery": meta.model_dump(mode="json"),
        }

    def _write_candidates(self, candidates: list[dict]) -> None:
        existing = (
            json.loads(self._comp_path.read_text(encoding="utf-8")) if self._comp_path.exists() else []
        )
        existing.extend(candidates)
        self._comp_path.write_text(
            json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def _write_report(self, report: DiscoveryReport) -> None:
        self._report_dir.mkdir(parents=True, exist_ok=True)
        (self._report_dir / f"{report.job_id}-report.json").write_text(
            report.model_dump_json(indent=2), encoding="utf-8"
        )
