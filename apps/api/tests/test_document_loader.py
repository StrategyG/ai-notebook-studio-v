from io import BytesIO
from zipfile import ZipFile

import pytest
from docx import Document
from pypdf import PdfWriter

from ai_notebook_api.rag.document_loader import (
    MAX_DOCX_ENTRIES,
    MAX_PDF_PAGES,
    MAX_UPLOAD_BYTES,
    DocumentParseError,
    extract_document_text,
    safe_filename,
)


def test_text_upload_extracts_utf8_and_preserves_text() -> None:
    result = extract_document_text("policy.md", b"\xef\xbb\xbf# Policy\n\nKeep data private.")
    assert result.text == "# Policy\n\nKeep data private."
    assert result.parser == "markdown-utf8"


def test_html_upload_ignores_script_and_style_content() -> None:
    result = extract_document_text(
        "page.html",
        b"<h1>Policy</h1><p>Keep tenant data private.</p><script>steal()</script><style>.x{}</style>",
        "text/html",
    )
    assert "Policy" in result.text
    assert "Keep tenant data private." in result.text
    assert "steal" not in result.text
    assert ".x" not in result.text


def test_docx_upload_extracts_paragraphs_and_table_cells() -> None:
    document = Document()
    document.add_paragraph("Tenant isolation policy")
    table = document.add_table(rows=1, cols=2)
    table.cell(0, 0).text = "Tenant A"
    table.cell(0, 1).text = "Tenant B"
    buffer = BytesIO()
    document.save(buffer)

    result = extract_document_text("policy.docx", buffer.getvalue())

    assert "Tenant isolation policy" in result.text
    assert "Tenant A | Tenant B" in result.text
    assert result.parser == "python-docx"


def test_upload_rejects_unsupported_types_and_oversized_payloads() -> None:
    with pytest.raises(DocumentParseError, match="Supported upload"):
        extract_document_text("program.exe", b"not executable")
    with pytest.raises(DocumentParseError, match="10 MB"):
        extract_document_text("large.txt", b"x" * (MAX_UPLOAD_BYTES + 1))


def test_upload_rejects_invalid_utf8_and_unsafe_docx() -> None:
    with pytest.raises(DocumentParseError, match="UTF-8"):
        extract_document_text("bad.txt", b"\xff\xfe")
    with pytest.raises(DocumentParseError):
        extract_document_text("bad.docx", b"not a zip archive")


def test_filename_is_reduced_to_a_safe_bounded_display_name() -> None:
    assert safe_filename("../../private/policy.txt") == "policy.txt"
    assert len(safe_filename("x" * 300 + ".txt")) == 200



def _pdf_bytes(*, pages: int = 1, password: str | None = None) -> bytes:
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=72, height=72)
    if password:
        writer.encrypt(password)
    buffer = BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def test_pdf_parser_rejects_encrypted_and_over_page_limit_documents() -> None:
    with pytest.raises(DocumentParseError, match="Encrypted"):
        extract_document_text("encrypted.pdf", _pdf_bytes(password="secret"))
    with pytest.raises(DocumentParseError, match="500-page"):
        extract_document_text("large.pdf", _pdf_bytes(pages=MAX_PDF_PAGES + 1))


def test_pdf_parser_rejects_scanned_or_empty_text_documents() -> None:
    with pytest.raises(DocumentParseError, match="no extractable text"):
        extract_document_text("scanned.pdf", _pdf_bytes())


def test_docx_parser_rejects_archive_entry_overflow_and_unsafe_paths() -> None:
    too_many = BytesIO()
    with ZipFile(too_many, "w") as archive:
        for index in range(MAX_DOCX_ENTRIES + 1):
            archive.writestr(f"entry-{index}.xml", b"")
    with pytest.raises(DocumentParseError, match="too many entries"):
        extract_document_text("many.docx", too_many.getvalue())

    unsafe = BytesIO()
    with ZipFile(unsafe, "w") as archive:
        archive.writestr("[Content_Types].xml", b"<Types/>")
        archive.writestr("../outside.xml", b"unsafe")
    with pytest.raises(DocumentParseError, match="unsafe path"):
        extract_document_text("unsafe.docx", unsafe.getvalue())


def test_document_parser_rejects_empty_content_and_extracted_text_overflow() -> None:
    with pytest.raises(DocumentParseError, match="empty"):
        extract_document_text("empty.txt", b"")
    with pytest.raises(DocumentParseError, match="1 MB character"):
        extract_document_text("long.txt", b"x" * 1_000_001)
