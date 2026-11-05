"""
Pulls plain text out of an uploaded old resume (.docx, .pdf, or .txt).

Works on in-memory file-like objects (BytesIO from an upload) rather than
disk paths, since this runs inside a web request.
"""
import asyncio
import io
import json
import os
import sys
import zipfile

import ftfy

import upload_screen

# Uploaded files are untrusted. A small .docx can unpack to gigabytes (a "zip bomb") and a PDF can have thousands of pages;
# either would tie up the server. These caps are far above any real resume or LinkedIn export.
MAX_DOCX_UNPACKED_BYTES = 100 * 1024 * 1024
MAX_DOCX_ENTRIES = 3000
MAX_PDF_PAGES = 150
EXTRACT_TIMEOUT_SECONDS = 30

# Files are read in a separate, resource-limited process (extractor_worker.py): a hostile or broken file can only hurt that child,
# which is killed when it overruns, never the web server. CT_ISOLATE_PARSING=0 reads in-process (the test suite does this to keep
# fast unit tests; the isolated path has its own tests).
# One at a time by default: the Render plan has 512 MB and each child needs roughly 100 MB. Raise CT_PARSE_CHILDREN only after checking memory.
ISOLATED_CHILDREN_AT_ONCE = max(1, int(os.environ.get("CT_PARSE_CHILDREN", "1")))
MAX_WORKER_OUTPUT_BYTES = 8 * 1024 * 1024
WORKER_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "extractor_worker.py")  # tests point this at a stand-in
_slots: asyncio.Semaphore | None = None
_slots_loop = None


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

    content = file_obj.getvalue()
    _refuse_if_zip_bomb(content)
    upload_screen.screen_docx(content)
    doc = Document(file_obj)

    def visible_text(paragraph) -> str:
        # text a reader cannot see on the page (hidden, white-on-white, 1-point) is not given to the AI
        return "".join(run.text for run in paragraph.runs if not upload_screen.docx_run_is_hidden(run))

    lines = []
    for para in doc.paragraphs:
        text = visible_text(para).strip()
        if text:
            lines.append(text)
    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                text = " ".join(visible_text(p).strip() for p in cell.paragraphs).strip()
                if text:
                    lines.append(text)
    return "\n".join(lines)


def extract_pdf_text(file_obj: io.BytesIO) -> str:
    from pypdf import PdfReader

    content = file_obj.getvalue()
    upload_screen.screen_pdf_bytes(content)
    reader = PdfReader(file_obj)
    if len(reader.pages) > MAX_PDF_PAGES:
        raise ValueError(f"That PDF has too many pages to read (more than {MAX_PDF_PAGES}).")
    upload_screen.screen_pdf_structure(reader)
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
    text, _ = upload_screen.strip_invisible(ftfy.fix_text(text))
    return text


def _worker_env() -> dict:
    """The child gets no secrets: a bug in a file reader cannot read the AI key or any other setting."""
    keep = ("PATH", "SYSTEMROOT", "TEMP", "TMP", "LANG", "LC_ALL", "VIRTUAL_ENV", "PYTHONPATH")
    env = {k: os.environ[k] for k in keep if k in os.environ}
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def _friendly_unreadable(filename: str) -> ValueError:
    suffix = filename.rsplit(".", 1)[-1].lower() if "." in filename else "file"
    return ValueError(f"Could not read that .{suffix} file - it may be corrupted, empty, or not a valid .{suffix} file.")


def _get_slots() -> asyncio.Semaphore:
    global _slots, _slots_loop
    loop = asyncio.get_running_loop()
    if _slots is None or _slots_loop is not loop:
        _slots, _slots_loop = asyncio.Semaphore(ISOLATED_CHILDREN_AT_ONCE), loop
    return _slots


async def _read_in_child(filename: str, content: bytes) -> str:
    worker = WORKER_PATH
    try:
        async with _get_slots():
            proc = await asyncio.create_subprocess_exec(
                sys.executable, worker, filename.rsplit(".", 1)[-1].lower() if "." in filename else "",
                stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
                env=_worker_env(), cwd=os.path.dirname(os.path.abspath(__file__)),
            )
            try:
                out, _ = await asyncio.wait_for(proc.communicate(content), EXTRACT_TIMEOUT_SECONDS)
            except asyncio.TimeoutError:
                try:
                    proc.kill()  # a hung file reader is ended outright, not left running
                except ProcessLookupError:
                    pass
                await proc.wait()
                raise ValueError("That file took too long to read. Try a smaller or simpler file.") from None
    except (OSError, NotImplementedError):
        raise _friendly_unreadable(filename) from None  # fail closed: never fall back to reading in this process
    lines = out[:MAX_WORKER_OUTPUT_BYTES].decode("utf-8", "replace").strip().splitlines()
    if not lines:
        raise _friendly_unreadable(filename)  # the child was stopped by its limits before it could answer
    try:
        result = json.loads(lines[-1])
    except ValueError:
        raise _friendly_unreadable(filename) from None
    if result.get("outcome") == "text":
        return result.get("text", "")
    if result.get("outcome") == "refused":
        raise ValueError(result.get("message") or "That file could not be read.")
    raise _friendly_unreadable(filename)


async def extract_text_async(filename: str, content: bytes) -> str:
    """Reads an upload without risk to the web server: in a separate, limited process that is killed on a timeout."""
    if os.environ.get("CT_ISOLATE_PARSING", "1") == "0":
        from starlette.concurrency import run_in_threadpool
        try:
            return await asyncio.wait_for(run_in_threadpool(extract_text, filename, content), EXTRACT_TIMEOUT_SECONDS)
        except asyncio.TimeoutError:
            raise ValueError("That file took too long to read. Try a smaller or simpler file.") from None
    return await _read_in_child(filename, content)
