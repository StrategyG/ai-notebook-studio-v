from __future__ import annotations

from dataclasses import dataclass
from html.parser import HTMLParser
from io import BytesIO
from pathlib import PurePosixPath
from zipfile import BadZipFile, ZipFile

MAX_UPLOAD_BYTES = 10 * 1024 * 1024
MAX_EXTRACTED_CHARS = 1_000_000
MAX_PDF_PAGES = 500
MAX_DOCX_ENTRIES = 512
MAX_DOCX_UNCOMPRESSED_BYTES = 30 * 1024 * 1024


class DocumentParseError(ValueError):
    """The uploaded document is unsupported, malformed, or exceeds safe limits."""


@dataclass(frozen=True, slots=True)
class ExtractedDocument:
    text: str
    parser: str
    media_type: str


class _HTMLTextExtractor(HTMLParser):
    _IGNORED_TAGS = frozenset({"script", "style", "noscript", "svg", "template"})

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._ignored_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() in self._IGNORED_TAGS:
            self._ignored_depth += 1
        elif self._ignored_depth == 0 and tag.lower() in {"p", "div", "br", "li", "tr", "h1", "h2", "h3"}:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in self._IGNORED_TAGS and self._ignored_depth:
            self._ignored_depth -= 1
        elif self._ignored_depth == 0 and tag.lower() in {"p", "div", "li", "tr", "h1", "h2", "h3"}:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._ignored_depth == 0 and data:
            self.parts.append(data)


def safe_filename(filename: str | None) -> str:
    """Keep only a bounded display name; never use the client path on disk."""
    raw = (filename or "uploaded-document").replace("\\", "/").split("/")[-1]
    cleaned = "".join(character for character in raw if character.isprintable()).strip()
    if not cleaned or cleaned in {".", ".."}:
        cleaned = "uploaded-document"
    return cleaned[:200]


def _bounded_text(value: str, *, parser: str, media_type: str) -> ExtractedDocument:
    normalized = value.replace("\x00", "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not normalized:
        raise DocumentParseError("The document contains no extractable text")
    if len(normalized) > MAX_EXTRACTED_CHARS:
        raise DocumentParseError("Extracted document text exceeds the 1 MB character limit")
    return ExtractedDocument(normalized, parser, media_type)


def _extract_docx(data: bytes, media_type: str) -> ExtractedDocument:
    try:
        with ZipFile(BytesIO(data)) as archive:
            members = archive.infolist()
            if len(members) > MAX_DOCX_ENTRIES:
                raise DocumentParseError("DOCX archive contains too many entries")
            total_uncompressed = sum(member.file_size for member in members)
            if total_uncompressed > MAX_DOCX_UNCOMPRESSED_BYTES:
                raise DocumentParseError("DOCX expanded content exceeds the safety limit")
            for member in members:
                path = PurePosixPath(member.filename)
                if path.is_absolute() or ".." in path.parts:
                    raise DocumentParseError("DOCX archive contains an unsafe path")
            if "[Content_Types].xml" not in {member.filename for member in members}:
                raise DocumentParseError("The uploaded file is not a valid DOCX document")
    except (BadZipFile, OSError) as exc:
        raise DocumentParseError("The uploaded DOCX document is malformed") from exc

    try:
        from docx import Document

        document = Document(BytesIO(data))
        parts = [paragraph.text for paragraph in document.paragraphs if paragraph.text.strip()]
        for table in document.tables:
            for row in table.rows:
                cells = [cell.text.strip() for cell in row.cells if cell.text.strip()]
                if cells:
                    parts.append(" | ".join(cells))
    except Exception as exc:
        raise DocumentParseError("The uploaded DOCX document could not be parsed") from exc
    return _bounded_text("\n".join(parts), parser="python-docx", media_type=media_type)


def _extract_pdf(data: bytes, media_type: str) -> ExtractedDocument:
    try:
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(data), strict=True)
        if reader.is_encrypted:
            raise DocumentParseError("Encrypted PDF documents are not accepted")
        if len(reader.pages) > MAX_PDF_PAGES:
            raise DocumentParseError("PDF exceeds the 500-page limit")
        parts: list[str] = []
        total_chars = 0
        for page in reader.pages:
            page_text = page.extract_text() or ""
            total_chars += len(page_text)
            if total_chars > MAX_EXTRACTED_CHARS:
                raise DocumentParseError("Extracted PDF text exceeds the 1 MB character limit")
            if page_text.strip():
                parts.append(page_text)
    except DocumentParseError:
        raise
    except Exception as exc:
        raise DocumentParseError("The uploaded PDF document is malformed or unreadable") from exc
    return _bounded_text("\n\n".join(parts), parser="pypdf", media_type=media_type)


def extract_document_text(filename: str | None, data: bytes, media_type: str | None = None) -> ExtractedDocument:
    """Extract text from bounded PDF, DOCX, HTML, Markdown, and plain-text uploads.

    The function never fetches URLs, executes embedded content, or writes the upload
    to disk. The caller must enforce the raw byte limit before invoking it.
    """
    if not isinstance(data, bytes) or not data:
        raise DocumentParseError("The uploaded file is empty")
    if len(data) > MAX_UPLOAD_BYTES:
        raise DocumentParseError("The uploaded file exceeds the 10 MB limit")

    name = safe_filename(filename)
    extension = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    declared_type = (media_type or "application/octet-stream").split(";", 1)[0].strip().lower()

    if extension in {"txt", "md", "markdown"}:
        try:
            content = data.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise DocumentParseError("Text documents must use UTF-8 encoding") from exc
        parser = "utf-8-text" if extension == "txt" else "markdown-utf8"
        return _bounded_text(content, parser=parser, media_type=declared_type)

    if extension in {"html", "htm"}:
        try:
            html = data.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise DocumentParseError("HTML documents must use UTF-8 encoding") from exc
        extractor = _HTMLTextExtractor()
        try:
            extractor.feed(html)
            extractor.close()
        except Exception as exc:
            raise DocumentParseError("The uploaded HTML document is malformed") from exc
        return _bounded_text("".join(extractor.parts), parser="html-text", media_type=declared_type)

    if extension == "pdf":
        return _extract_pdf(data, declared_type)

    if extension == "docx":
        return _extract_docx(data, declared_type)

    raise DocumentParseError("Supported upload types are PDF, DOCX, HTML, Markdown, and TXT")
