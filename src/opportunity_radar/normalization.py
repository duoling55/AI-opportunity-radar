from __future__ import annotations

import hashlib
import re
import unicodedata
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from opportunity_radar.models import PolicyCandidate, PolicyDocument


def normalize_text(value: str) -> str:
    """Collapse whitespace so formatting-only revisions retain one content hash."""
    return re.sub(r"\s+", " ", value).strip()


def canonical_url(value: str) -> str:
    """Remove tracking components while retaining query parameters that identify a page."""
    parts = urlsplit(value)
    identity_query = urlencode(
        [
            (key, item)
            for key, item in parse_qsl(parts.query, keep_blank_values=True)
            if key.casefold() != "tracking"
            and not key.casefold().startswith("utm_")
        ],
        doseq=True,
    )
    return urlunsplit(
        (
            parts.scheme.lower(),
            parts.netloc.lower(),
            parts.path.rstrip("/"),
            identity_query,
            "",
        )
    )


def normalize_document_number(value: str) -> str:
    """Normalize equivalent official document-number bracket and spacing forms."""
    normalized = unicodedata.normalize("NFKC", value).upper()
    normalized = normalized.replace("[", "〔").replace("]", "〕")
    return re.sub(r"\s+", "", normalized)


def make_policy_id(
    candidate: PolicyCandidate, document_number: str | None = None
) -> str:
    """Create a stable source-scoped identifier using the specification priority."""
    if document_number and normalize_document_number(document_number):
        identity = f"document:{normalize_document_number(document_number)}"
    elif str(candidate.detail_url).strip():
        identity = f"url:{canonical_url(str(candidate.detail_url))}"
    else:
        published = candidate.published_at.isoformat() if candidate.published_at else ""
        identity = f"title-date:{normalize_text(candidate.title)}|{published}"
    seed = f"{candidate.source_id}|{identity}"
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()[:24]


def content_hash(text: str) -> str:
    """Hash normalized policy text for incremental processing decisions."""
    return hashlib.sha256(normalize_text(text).encode("utf-8")).hexdigest()


def cross_source_key(document: PolicyDocument) -> str:
    """Identify official reposts independently of their hosting source."""
    if document.document_number:
        seed = f"document:{normalize_document_number(document.document_number)}"
    else:
        published = document.publish_date.isoformat() if document.publish_date else ""
        seed = (
            f"title-date-content:{normalize_text(document.title)}|"
            f"{published}|{document.content_hash}"
        )
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()
