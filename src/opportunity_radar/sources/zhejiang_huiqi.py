from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse

from opportunity_radar.models import PolicyCandidate, PolicyDocument
from opportunity_radar.normalization import content_hash, make_policy_id, normalize_text
from opportunity_radar.parsing.snapshot import save_snapshot
from opportunity_radar.sources.base import GenericHtmlSource

API_BASE_URL = "https://zj87.jxt.zj.gov.cn/webapi/"
LIST_API = f"{API_BASE_URL}extMsPolicyInfo/list"
DETAIL_API = f"{API_BASE_URL}PolicyInfo/pcConsultDetail"
DETAIL_PAGE_URL = "https://zj87.jxt.zj.gov.cn/zjhqpt/views/policy-zw/detail.html"
PAGE_SIZE = 100


def _parse_api_date(value: object) -> date | None:
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def _api_text(*values: object) -> str:
    return next(
        (
            normalized
            for value in values
            if isinstance(value, str) and (normalized := normalize_text(value))
        ),
        "",
    )


class ZhejiangHuiqiSource(GenericHtmlSource):
    detail_content_selectors = ("#policy-detail", ".policy-detail", "article", "main")

    def discover(self, start: date, end: date) -> list[PolicyCandidate]:
        found: dict[str, PolicyCandidate] = {}
        page_num = 1

        while True:
            response = self.client.post(
                LIST_API,
                {
                    "keywords": "",
                    "policyCategory": "",
                    "applyAreaId": "",
                    "departmentId": "",
                    "isDeclare": "",
                    "orderby": 2,
                    "pageNum": page_num,
                    "pageSize": PAGE_SIZE,
                    "declareClick": "",
                },
            )
            payload = response.json()
            if payload.get("status") != 1:
                raise RuntimeError("Zhejiang Huiqi list API returned an unsuccessful status")
            body = payload.get("body")
            if not isinstance(body, dict):
                raise TypeError("Zhejiang Huiqi list API returned an invalid body")
            items = body.get("list")
            if not isinstance(items, list):
                raise TypeError("Zhejiang Huiqi list API returned an invalid list")

            current_or_newer = False
            for item in items:
                if not isinstance(item, dict):
                    continue
                policy_id = item.get("id")
                title = item.get("title")
                published_at = _parse_api_date(item.get("publishDate"))
                if policy_id is None or not isinstance(title, str) or not title.strip() or not published_at:
                    continue
                if published_at >= start:
                    current_or_newer = True
                if not start <= published_at <= end:
                    continue
                detail_url = f"{DETAIL_PAGE_URL}?{urlencode({'id': str(policy_id)})}"
                found[str(policy_id)] = PolicyCandidate(
                    source_id=self.config.source_id,
                    title=title.strip(),
                    detail_url=detail_url,
                    published_at=published_at,
                )

            total_pages = body.get("totalPage")
            if not isinstance(total_pages, int) or page_num >= total_pages or not items:
                break
            if not current_or_newer:
                break
            page_num += 1

        return list(found.values())

    def fetch_document(
        self,
        candidate: PolicyCandidate,
        collected_at: datetime,
        raw_dir: Path,
    ) -> PolicyDocument:
        policy_id = parse_qs(urlparse(str(candidate.detail_url)).query).get("id", [""])[0]
        if not policy_id:
            raise ValueError("Zhejiang Huiqi detail URL is missing the policy id")

        response = self.client.post(DETAIL_API, {"id": policy_id})
        payload = response.json()
        if payload.get("status") != 1:
            raise RuntimeError("Zhejiang Huiqi detail API returned an unsuccessful status")
        body = payload.get("body")
        if not isinstance(body, dict):
            raise TypeError("Zhejiang Huiqi detail API returned an invalid body")

        title = _api_text(body.get("title"), candidate.title)
        raw_text = _api_text(body.get("content_trim"), body.get("content"), body.get("intercontent"))
        document_number = _api_text(body.get("code")) or None
        snapshot = save_snapshot(
            raw_dir,
            make_policy_id(candidate, document_number),
            "json",
            json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8"),
        )

        return PolicyDocument(
            policy_id=make_policy_id(candidate, document_number),
            source_id=self.config.source_id,
            source_name=self.config.display_name,
            region=self.config.region,
            title=title,
            detail_url=candidate.detail_url,
            publisher=_api_text(body.get("department")) or None,
            document_number=document_number,
            publish_date=_parse_api_date(body.get("publishdate")) or candidate.published_at,
            raw_text=raw_text,
            normalized_text=raw_text,
            attachment_errors=(
                ["政策详情接口未返回可解析正文"] if not raw_text else []
            ),
            collected_at=collected_at,
            content_hash=content_hash(raw_text),
            snapshot_path=snapshot.as_posix(),
        )
