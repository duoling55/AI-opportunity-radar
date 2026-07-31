from datetime import UTC, date, datetime
from io import BytesIO
from pathlib import Path

from docx import Document
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from opportunity_radar.config import SourceConfig
from opportunity_radar.http import OfficialHttpClient
from opportunity_radar.models import PolicyCandidate
from opportunity_radar.normalization import content_hash
from opportunity_radar.parsing.html import DocumentRetriever, parse_html
from opportunity_radar.sources.base import GenericHtmlSource


def _config() -> SourceConfig:
    return SourceConfig("miit", "工信部", "全国", (), ("www.miit.gov.cn",), request_interval_seconds=0)


def _text_pdf(value: str) -> bytes:
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
    content.set_data(f"BT /F1 12 Tf 72 720 Td ({value}) Tj ET".encode())
    page[NameObject("/Contents")] = writer._add_object(content)
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


def test_parse_html_extracts_explicit_metadata_and_official_attachments() -> None:
    candidate = PolicyCandidate(
        source_id="miit",
        title="候选标题",
        detail_url="https://www.miit.gov.cn/art/1.html",
    )
    html = Path("tests/fixtures/policy.html").read_text(encoding="utf-8")
    collected_at = datetime(2026, 7, 29, tzinfo=UTC)

    document = parse_html(candidate, _config(), html, collected_at, Path("data/raw/x.html"))

    assert document.title == "设备更新通知"
    assert document.publisher == "工业和信息化部"
    assert document.document_number == "工信部联装〔2026〕1号"
    assert document.publish_date == date(2026, 7, 20)
    assert document.effective_date == date(2026, 8, 1)
    assert "技术改造" in document.raw_text
    assert document.normalized_text == document.raw_text
    assert [str(url) for url in document.attachment_urls] == [
        "https://www.miit.gov.cn/files/notice.pdf",
        "https://www.miit.gov.cn/files/form.docx",
    ]
    assert document.collected_at == collected_at
    assert document.content_hash == content_hash(document.normalized_text)
    assert document.snapshot_path == "data/raw/x.html"


def test_parse_html_keeps_unknown_metadata_empty_and_candidate_date() -> None:
    candidate = PolicyCandidate(
        source_id="miit",
        title="候选标题",
        detail_url="https://www.miit.gov.cn/art/1.html",
        published_at=date(2026, 7, 1),
    )

    document = parse_html(
        candidate,
        _config(),
        "<main><p>正文没有明确元数据。</p></main>",
        datetime(2026, 7, 29, tzinfo=UTC),
        Path("data/raw/x.html"),
    )

    assert document.title == "候选标题"
    assert document.publisher is None
    assert document.document_number is None
    assert document.publish_date == date(2026, 7, 1)
    assert document.effective_date is None


def test_parse_html_uses_rendered_page_title_when_h1_is_absent() -> None:
    candidate = PolicyCandidate(
        source_id="miit",
        title="列表中的冗长标题和摘要",
        detail_url="https://www.miit.gov.cn/art/1.html",
    )

    document = parse_html(
        candidate,
        _config(),
        '<div class="page-title">准确政策标题</div><main>政策正文。</main>',
        datetime(2026, 7, 29, tzinfo=UTC),
        Path("data/raw/x.html"),
    )

    assert document.title == "准确政策标题"


def test_parse_html_prefers_article_body_over_main_and_page_chrome() -> None:
    candidate = PolicyCandidate(
        source_id="miit", title="候选标题", detail_url="https://www.miit.gov.cn/art/1.html"
    )
    html = """
    <body>
      <nav>网站导航和栏目</nav>
      <p>发布机关：工业和信息化部</p>
      <main><p>主栏摘要，不应进入政策正文。</p></main>
      <article><p>政策正文第一段。</p><p>政策正文第二段。</p></article>
      <footer>版权所有，不应进入政策正文。</footer>
    </body>
    """

    document = parse_html(
        candidate,
        _config(),
        html,
        datetime(2026, 7, 29, tzinfo=UTC),
        Path("data/raw/x.html"),
    )

    assert document.publisher == "工业和信息化部"
    assert document.raw_text == "政策正文第一段。 政策正文第二段。"
    assert document.normalized_text == document.raw_text
    assert document.content_hash == content_hash("政策正文第一段。 政策正文第二段。")


def test_document_retriever_saves_response_and_preserves_provenance(httpx_mock, tmp_path: Path) -> None:
    candidate = PolicyCandidate(
        source_id="miit", title="候选标题", detail_url="https://www.miit.gov.cn/art/1.html"
    )
    html = Path("tests/fixtures/policy.html").read_text(encoding="utf-8")
    document_file = Document()
    document_file.add_paragraph("附件中的设备更新申报条件")
    docx = BytesIO()
    document_file.save(docx)
    httpx_mock.add_response(url=str(candidate.detail_url), text=html)
    httpx_mock.add_response(
        url="https://www.miit.gov.cn/files/notice.pdf",
        content=b"not a readable pdf",
        headers={"Content-Type": "application/pdf"},
    )
    httpx_mock.add_response(
        url="https://www.miit.gov.cn/files/form.docx",
        content=docx.getvalue(),
        headers={
            "Content-Type": (
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            )
        },
    )
    source = GenericHtmlSource(_config(), OfficialHttpClient(_config()))

    document = DocumentRetriever().fetch_document(
        source, candidate, datetime(2026, 7, 29, tzinfo=UTC), tmp_path
    )

    assert Path(document.snapshot_path).read_bytes() == html.encode()
    assert document.detail_url == candidate.detail_url
    assert "附件中的设备更新申报条件" in document.normalized_text
    assert document.content_hash == content_hash(document.normalized_text)
    assert len(document.attachment_snapshot_paths) == 2
    assert all(Path(path).exists() for path in document.attachment_snapshot_paths)
    assert len(document.attachment_errors) == 1
    assert document.attachment_errors[0].startswith("附件解析失败（notice.pdf）：")


def test_document_retriever_does_not_download_legacy_doc_and_records_review_reason(
    httpx_mock, tmp_path: Path
) -> None:
    candidate = PolicyCandidate(
        source_id="miit",
        title="候选标题",
        detail_url="https://www.miit.gov.cn/art/legacy.html",
    )
    html = """
    <article><p>支持设备更新。</p></article>
    <a href="/files/legacy.doc">旧版附件</a>
    """
    httpx_mock.add_response(url=str(candidate.detail_url), text=html)
    source = GenericHtmlSource(_config(), OfficialHttpClient(_config()))

    document = DocumentRetriever().fetch_document(
        source, candidate, datetime(2026, 7, 29, tzinfo=UTC), tmp_path
    )

    assert [str(request.url) for request in httpx_mock.get_requests()] == [
        str(candidate.detail_url)
    ]
    assert document.attachment_snapshot_paths == []
    assert document.attachment_errors == [
        "旧版 Word .doc 附件不自动下载或解析（legacy.doc）"
    ]


def test_document_retriever_includes_allowlisted_pdf_text_in_hash_and_snapshot(
    httpx_mock, tmp_path: Path
) -> None:
    candidate = PolicyCandidate(
        source_id="miit",
        title="候选标题",
        detail_url="https://www.miit.gov.cn/art/pdf.html",
    )
    html = '<article>政策正文。</article><a href="/files/rules.pdf">附件</a>'
    httpx_mock.add_response(url=str(candidate.detail_url), text=html)
    httpx_mock.add_response(
        url="https://www.miit.gov.cn/files/rules.pdf",
        content=_text_pdf("PDF attachment evidence"),
        headers={"Content-Type": "application/octet-stream"},
    )
    source = GenericHtmlSource(_config(), OfficialHttpClient(_config()))

    document = DocumentRetriever().fetch_document(
        source, candidate, datetime(2026, 7, 29, tzinfo=UTC), tmp_path
    )

    assert "PDF attachment evidence" in document.normalized_text
    assert document.content_hash == content_hash(document.normalized_text)
    assert Path(document.attachment_snapshot_paths[0]).read_bytes().startswith(b"%PDF")
    assert document.attachment_errors == []
