from __future__ import annotations

from io import BytesIO

from docx import Document
from pypdf import PdfReader


def extract_attachment_text(content_type: str, body: bytes) -> str:
    """Extract text from supported official attachment formats."""
    normalized_content_type = content_type.lower()
    if "pdf" in normalized_content_type:
        return "\n".join(
            page.extract_text() or "" for page in PdfReader(BytesIO(body)).pages
        ).strip()
    if "application/msword" in normalized_content_type:
        raise ValueError("legacy Word .doc attachments are not supported")
    if "docx" in normalized_content_type or "officedocument.wordprocessingml" in normalized_content_type:
        return "\n".join(paragraph.text for paragraph in Document(BytesIO(body)).paragraphs).strip()
    raise ValueError(f"unsupported attachment content type: {content_type}")
