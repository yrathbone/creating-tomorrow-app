"""
Pulls plain text out of an uploaded old resume (.docx, .pdf, or .txt).

Works on in-memory file-like objects (BytesIO from an upload) rather than
disk paths, since this runs inside a web request.
"""
import io

import ftfy


def extract_docx_text(file_obj: io.BytesIO) -> str:
    from docx import Document

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
