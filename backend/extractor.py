"""
Pulls plain text out of an uploaded old resume (.docx, .pdf, or .txt).

Works on in-memory file-like objects (BytesIO from an upload) rather than
disk paths, since this runs inside a web request.
"""
import asyncio
import io
import zipfile

import ftfy
from starlette.concurrency import run_in_threadpool

# Uploaded files are untrusted. A small .docx can unpack to gigabytes (a "zip bomb") and a PDF can have thousands of pages;
# either would tie up the server. These caps are far above any real resume or LinkedIn export.
MAX_DOCX_UNPACKED_BYTES = 100 * 1024 * 1024
MAX_DOCX_ENTRIES = 3000
MAX_PDF_PAGES = 150
EXTRACT_TIMEOUT_SECONDS = 30


def _refuse_if_zip_bomb(content: bytes) -> None:
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as z:
            infos = z.infolist()
    except zipfile.BadZipFile:
        return  # python-docx will report it as an unreadable file
    if len(infos) > MAX_DOCX_ENTRIES or sum(i.file_size for i in infos) > MAX_DOCX_UNPACKED_BYTES:
        raise ValueError("That Word file is too large or complex to read. Try saving it again as a simpler file.")


def extract_docx_text(file_obj: io.BytesIO) -> str:
    from docx import Document

    _refuse_if_zip_bomb(file_obj.getvalue())
    doc = Document(file_obj)
    lines = []
    for para in doc.paragraphs:
        text = para.text.strip()
        if text:
            lines.append(text)
    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                text = cell.text.strip()
                if text:
                    lines.append(text)
    return "\n".join(lines)


def extract_pdf_text(file_obj: io.BytesIO) -> str:
    from pypdf import PdfReader

    reader = PdfReader(file_obj)
    if len(reader.pages) > MAX_PDF_PAGES:
        raise ValueError(f"That PDF has too many pages to read (more than {MAX_PDF_PAGES}).")
    lines = []
    for page in reader.pages:
        text = page.extract_text() or ""
        for line in text.splitlines():
            line = line.strip()
            if line:
                lines.append(line)
    return "\n".join(lines)


def extract_text(filename: str, content: bytes) -> str:
    suffix = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    file_obj = io.BytesIO(content)

    try:
        if suffix == "docx":
            text = extract_docx_text(file_obj)
        elif suffix == "pdf":
            text = extract_pdf_text(file_obj)
        elif suffix == "txt":
            text = content.decode("utf-8", errors="replace")
        else:
            raise ValueError(f"Unsupported file type: .{suffix} (expected .docx, .pdf, or .txt)")
    except ValueError:
        raise
    except Exception as e:
        # python-docx/pypdf raise their own library-specific exceptions
        # (BadZipFile, PdfStreamError, EmptyFileError, ...) for a corrupted,
        # empty, or not-actually-a-.docx/.pdf file - none of those are
        # ValueError, so every caller's `except ValueError` block (main.py)
        # was letting them through as an unhandled 500 instead of the
        # intended friendly 400. Converting every extraction failure to
        # ValueError here fixes that once, for every caller, rather than
        # needing a broader except clause repeated at each of the 6 call
        # sites across main.py.
        raise ValueError(
            f"Could not read that .{suffix} file - it may be corrupted, empty, or not a valid .{suffix} file."
        ) from e

    # Some PDF generators embed dashes/curly quotes as UTF-8 bytes run through
    # a Latin-1 font encoding, so extracted text can come out as mojibake
    # (e.g. an em-dash becomes "â€"") even though pypdf itself decoded the
    # PDF correctly - ftfy detects and reverses this encoding mismatch.
    return ftfy.fix_text(text)


async def extract_text_async(filename: str, content: bytes) -> str:
    """extract_text on a worker thread, so a slow or heavy file cannot freeze every other visitor, with a time limit."""
    try:
        return await asyncio.wait_for(run_in_threadpool(extract_text, filename, content), EXTRACT_TIMEOUT_SECONDS)
    except asyncio.TimeoutError:
        raise ValueError("That file took too long to read. Try a smaller or simpler file.") from None
