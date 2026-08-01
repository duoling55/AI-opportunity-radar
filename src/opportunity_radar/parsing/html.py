from __future__ import annotations

import re
from datetime import date, datetime
from pathlib import Path
from urllib.parse import unquote, urljoin, urlparse

from bs4 import BeautifulSoup

from opportunity_radar.config import SourceConfig
from opportunity_radar.models import PolicyCandidate, PolicyDocument
from opportunity_radar.normalization import content_hash, make_policy_id, normalize_text
from opportunity_radar.parsing.attachments import extract_attachment_text
from opportunity_radar.parsing.snapshot import save_snapshot
from opportunity_radar.sources.base import GenericHtmlSource

DATE = re.compile(r"(20\d{2})[-/.年](\d{1,2})[-/.月](\d{1,2})")
DOCUMENT_NUMBER = re.compile(r"[\u4e00-\u9fffA-Za-z0-9]+(?:〔|\[)20\d{2}(?:〕|\])\d+号")


def _explicit_date(text: str, labels: tuple[str, ...]) -> date | None:
    for label in labels:
        match = re.search(rf"{re.escape(label)}\s*[：:]?\s*{DATE.pattern}", text)
        if match:
            try:
                return date(*map(int, match.groups()))
            except ValueError:
                return None
    return None


def _publisher(text: str) -> str | None:
    match = re.search(r"(?:发布机关|发布单位|发文机关)\s*[：:]\s*([^\n]+)", text)
    return normalize_text(match.group(1)) if match else None


def _official_attachment_urls(
    soup: BeautifulSoup, detail_url: str, allowed_domains: tuple[str, ...]
) -> list[str]:
    attachment_urls: list[str] = []
    for anchor in soup.select("a[href]"):
        href = anchor.get("href")
        if not isinstance(href, str):
            continue
        resolved_url = urljoin(detail_url, href)
        if urlparse(resolved_url).hostname not in allowed_domains:
            continue
        path = urlparse(resolved_url).path.lower()
        if path.endswith((".pdf", ".doc", ".docx")):
            attachment_urls.append(resolved_url)
    return attachment_urls


def parse_html(
    candidate: PolicyCandidate,
    config: SourceConfig,
    html: str,
    collected_at: datetime,
    snapshot_path: Path,
    content_selectors: tuple[str, ...] = ("article", "main"),
) -> PolicyDocument:
    """Normalize an official detail page without inventing unavailable metadata."""
    soup = BeautifulSoup(html, "html.parser")
    title_node = soup.find("h1") or soup.select_one(".page-title")
    title = title_node.get_text(" ", strip=True) if title_node else candidate.title
    metadata_text = (soup.body or soup).get_text("\n", strip=True)
    content_node = next(
        (node for selector in content_selectors if (node := soup.select_one(selector))),
        None,
    )
    content_node = content_node or soup.body or soup
    raw_text = normalize_text(content_node.get_text(" ", strip=True))
    document_number = DOCUMENT_NUMBER.search(metadata_text)

    resolved_document_number = document_number.group(0) if document_number else None
    return PolicyDocument(
        policy_id=make_policy_id(candidate, resolved_document_number),
        source_id=config.source_id,
        source_name=config.display_name,
        region=config.region,
        title=title,
        detail_url=candidate.detail_url,
        publisher=_publisher(metadata_text),
        document_number=resolved_document_number,
        publish_date=_explicit_date(metadata_text, ("发布时间", "发布日期", "印发日期"))
        or candidate.published_at,
        effective_date=_explicit_date(metadata_text, ("施行日期", "生效日期")),
        application_start_date=_explicit_date(metadata_text, ("申报开始日期", "申请开始日期")),
        application_end_date=_explicit_date(metadata_text, ("申报截止日期", "申请截止日期")),
        raw_text=raw_text,
        normalized_text=raw_text,
        attachment_urls=_official_attachment_urls(
            soup, str(candidate.detail_url), config.allowed_domains
        ),
        collected_at=collected_at,
        content_hash=content_hash(raw_text),
        snapshot_path=snapshot_path.as_posix(),
    )


class DocumentRetriever:
    """Fetch and snapshot an official detail page before parsing it."""

    def fetch_document(
        self,
        source: GenericHtmlSource,
        candidate: PolicyCandidate,
        collected_at: datetime,
        raw_dir: Path,
    ) -> PolicyDocument:
        source_fetch_document = getattr(source, "fetch_document", None)
        if callable(source_fetch_document):
            return source_fetch_document(candidate, collected_at, raw_dir)
        response = source.client.get(str(candidate.detail_url))
        snapshot = save_snapshot(raw_dir, make_policy_id(candidate), "html", response.content)
        document = parse_html(
            candidate,
            source.config,
            response.text,
            collected_at,
            snapshot,
            source.detail_content_selectors,
        )
        text_parts = [document.normalized_text]
        snapshot_paths: list[str] = []
        errors: list[str] = []

        for index, attachment_url in enumerate(document.attachment_urls, start=1):
            url = str(attachment_url)
            filename = Path(unquote(urlparse(url).path)).name or f"attachment-{index}"
            suffix = Path(filename).suffix.lower().lstrip(".")
            if suffix == "doc":
                errors.append(f"旧版 Word .doc 附件不自动下载或解析（{filename}）")
                continue
            try:
                attachment_response = source.client.get(url)
                attachment_snapshot = save_snapshot(
                    raw_dir,
                    f"{document.policy_id}-attachment-{index}",
                    suffix or "bin",
                    attachment_response.content,
                )
                snapshot_paths.append(attachment_snapshot.as_posix())
                content_type = attachment_response.headers.get("Content-Type", "")
                if not content_type or "octet-stream" in content_type.lower():
                    content_type = {
                        "pdf": "application/pdf",
                        "docx": (
                            "application/vnd.openxmlformats-officedocument."
                            "wordprocessingml.document"
                        ),
                    }.get(suffix, content_type)
                attachment_text = extract_attachment_text(
                    content_type,
                    attachment_response.content,
                )
                if not attachment_text:
                    raise ValueError("附件未提取到文本，可能需要 OCR 或人工复核")
                text_parts.append(f"[附件 {index}：{filename}]\n{attachment_text}")
            except PermissionError:
                raise
            except Exception as error:  # noqa: BLE001 - retain page and attachment failure
                errors.append(
                    f"附件解析失败（{filename}）：{type(error).__name__}: {error}"
                )

        normalized_text = normalize_text("\n\n".join(text_parts))
        return document.model_copy(
            update={
                "normalized_text": normalized_text,
                "content_hash": content_hash(normalized_text),
                "attachment_snapshot_paths": snapshot_paths,
                "attachment_errors": errors,
            }
        )
