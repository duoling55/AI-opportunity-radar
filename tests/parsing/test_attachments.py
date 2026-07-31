from io import BytesIO

import pytest
from docx import Document
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from opportunity_radar.parsing.attachments import extract_attachment_text


def test_extract_attachment_text_reads_docx_paragraphs() -> None:
    document = Document()
    document.add_paragraph("设备更新申报材料")
    content = BytesIO()
    document.save(content)

    assert extract_attachment_text(
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document", content.getvalue()
    ) == "设备更新申报材料"


def test_extract_attachment_text_reads_pdf_pages() -> None:
    writer = PdfWriter()
    page = writer.add_blank_page(width=612, height=792)
    font = writer._add_object(
        DictionaryObject(
            {
                NameObject("/Type"): NameObject("/Font"),
                NameObject("/Subtype"): NameObject("/Type1"),
                NameObject("/BaseFont"): NameObject("/Helvetica"),
            }
        )
    )
    page[NameObject("/Resources")] = DictionaryObject(
        {NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})}
    )
    content = DecodedStreamObject()
    content.set_data(b"BT /F1 12 Tf 72 720 Td (PDF policy attachment) Tj ET")
    page[NameObject("/Contents")] = writer._add_object(content)
    pdf = BytesIO()
    writer.write(pdf)

    assert extract_attachment_text("application/pdf", pdf.getvalue()) == "PDF policy attachment"


def test_extract_attachment_text_rejects_unsupported_content_type() -> None:
    with pytest.raises(ValueError, match="unsupported attachment"):
        extract_attachment_text("text/plain", b"not an attachment")


def test_extract_attachment_text_rejects_legacy_word_doc_clearly() -> None:
    with pytest.raises(ValueError, match="legacy Word .doc"):
        extract_attachment_text("application/msword", b"legacy document")
