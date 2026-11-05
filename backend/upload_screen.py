"""Screening of uploaded files before they are read (Word, PDF, plain text).

A resume never needs macros, scripts, embedded files or remote templates, so a file that carries any of them is refused with a plain
message instead of being opened further. Everything here works on the raw bytes and the file's own structure: nothing is executed,
written to disk, or sent anywhere. This is NOT a signature (antivirus) scan; it removes the active-content routes that malicious
documents rely on, and the reader itself runs in a separate, resource-limited process (see extractor.py).

Also here: text clean-up for what the AI will read. Invisible characters and text a person cannot see on the page (hidden or
white-on-white or 1-point text in a Word file) are dropped, so a document cannot smuggle instructions to the AI that the candidate
never sees.
"""
import io
import re
import unicodedata
import zipfile

REFUSED_WORD = "That Word file contains macros, embedded objects or remote content, which we can't accept. Save it again as a plain .docx, or paste the text instead."
REFUSED_PDF = "That PDF contains scripts, attachments or interactive content, which we can't accept. Save or print it again as a plain PDF, or paste the text instead."

# Word: parts and relationship types that carry code or remote content.
_DOCX_BAD_PART = re.compile(r"(^|/)(vbaProject[^/]*|vbaData[^/]*)$|^word/(embeddings|activeX|macrosheets)/|\.bin$|^customUI/", re.I)
_DOCX_BAD_REL_TYPE = re.compile(r"/(oleObject|package|attachedTemplate|frame|subDocument|externalLink|vbaProject|control|aFChunk)$", re.I)
_REL = re.compile(r"<Relationship\b([^>]*)>", re.I)
_ATTR = re.compile(r'(\w+)\s*=\s*"([^"]*)"')

# PDF: names that start code, launch programs, carry files or post data. Matched after undoing #xx name escapes.
_PDF_BAD_NAMES = (b"/JavaScript", b"/JS", b"/Launch", b"/EmbeddedFile", b"/EmbeddedFiles", b"/RichMedia", b"/XFA", b"/SubmitForm",
                  b"/ImportData", b"/GoToE", b"/GoToR", b"/Sound", b"/Movie", b"/FileAttachment")
_NAME_ESCAPE = re.compile(rb"#([0-9A-Fa-f]{2})")


def _unescape_names(data: bytes) -> bytes:
    return _NAME_ESCAPE.sub(lambda m: bytes([int(m.group(1), 16)]), data)


def screen_docx(content: bytes) -> None:
    """Raises ValueError (plain message) if the Word file has macros, embedded objects or remote parts. Not-a-zip is left to the reader."""
    try:
        zf = zipfile.ZipFile(io.BytesIO(content))
    except zipfile.BadZipFile:
        return
    with zf:
        names = zf.namelist()
        for name in names:
            if _DOCX_BAD_PART.search(name):
                raise ValueError(REFUSED_WORD)
        try:
            types = zf.read("[Content_Types].xml").decode("utf-8", "replace")
        except KeyError:
            types = ""
        if re.search(r"macroEnabled|vnd\.ms-office\.vbaProject|vnd\.ms-word\.vbaData", types, re.I):
            raise ValueError(REFUSED_WORD)
        for name in names:
            if not name.endswith(".rels"):
                continue
            for rel in _REL.findall(zf.read(name).decode("utf-8", "replace")):
                attrs = dict(_ATTR.findall(rel))
                if attrs.get("TargetMode", "").lower() == "external" and _DOCX_BAD_REL_TYPE.search(attrs.get("Type", "")):
                    raise ValueError(REFUSED_WORD)
                if _DOCX_BAD_REL_TYPE.search(attrs.get("Type", "")):  # an object or template relationship even when it points inside the file
                    raise ValueError(REFUSED_WORD)


def screen_pdf_bytes(content: bytes) -> None:
    """Fast pass over the raw bytes (names are matched after undoing #xx escapes). The structural pass is screen_pdf_structure."""
    flat = _unescape_names(content)
    for bad in _PDF_BAD_NAMES:
        # a name ends at a delimiter or whitespace, so /JS does not match /JSON-looking text and /EmbeddedFile does not need /EmbeddedFiles
        if re.search(re.escape(bad) + rb"(?![A-Za-z0-9])", flat):
            raise ValueError(REFUSED_PDF)


def screen_pdf_structure(reader) -> None:
    """Walks the parts of a parsed PDF where actions live, including objects hidden inside compressed object streams."""
    def get(obj):
        try:
            return obj.get_object() if hasattr(obj, "get_object") else obj
        except Exception:
            return None

    def bad_action(action) -> bool:
        action = get(action)
        if not hasattr(action, "get"):
            return False
        kind = str(get(action.get("/S")) or "")
        if kind in ("/JavaScript", "/Launch", "/SubmitForm", "/ImportData", "/GoToE", "/GoToR", "/Rendition", "/Sound", "/Movie"):
            return True
        return "/JS" in action or bool(bad_action(action.get("/Next")))

    root = get(reader.trailer.get("/Root")) if hasattr(reader, "trailer") else None
    if root is None or not hasattr(root, "get"):
        return
    if bad_action(root.get("/OpenAction")) or get(root.get("/AA")):
        raise ValueError(REFUSED_PDF)
    names = get(root.get("/Names"))
    if hasattr(names, "get") and (names.get("/JavaScript") is not None or names.get("/EmbeddedFiles") is not None):
        raise ValueError(REFUSED_PDF)
    acro = get(root.get("/AcroForm"))
    if hasattr(acro, "get") and acro.get("/XFA") is not None:
        raise ValueError(REFUSED_PDF)
    for page in reader.pages:
        if get(page.get("/AA")):
            raise ValueError(REFUSED_PDF)
        annots = get(page.get("/Annots")) or []
        for annot in annots:
            annot = get(annot)
            if not hasattr(annot, "get"):
                continue
            if str(get(annot.get("/Subtype")) or "") in ("/FileAttachment", "/Sound", "/Movie", "/RichMedia", "/Screen"):
                raise ValueError(REFUSED_PDF)
            if bad_action(annot.get("/A")) or get(annot.get("/AA")):
                raise ValueError(REFUSED_PDF)


# ---- what the AI will read -----------------------------------------------------------------------------------------------

_KEEP_FORMAT = {" ", "­"}  # no-break space and soft hyphen are ordinary in real documents


def strip_invisible(text: str) -> tuple[str, int]:
    """Removes zero-width, bidirectional-control and other invisible format characters. Returns (clean text, how many were removed)."""
    out, removed = [], 0
    for ch in text:
        cat = unicodedata.category(ch)
        if cat == "Cf" and ch not in _KEEP_FORMAT:
            removed += 1
            continue
        if cat == "Cc" and ch not in "\n\r\t":
            removed += 1
            continue
        out.append(ch)
    return "".join(out), removed


_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def _shaded(element) -> bool:
    """True if the run, its paragraph or its table cell has a real (not white or automatic) background fill, so white text on it is readable."""
    node = element
    while node is not None:
        for shd in node.iter(_W + "shd") if node.tag in (_W + "rPr", _W + "pPr", _W + "tcPr") else []:
            fill = (shd.get(_W + "fill") or "auto").upper()
            if fill not in ("AUTO", "FFFFFF"):
                return True
        node = node.getparent()
    return False


def _formatting_shaded(r) -> bool:
    node = r
    while node is not None:
        for tag in ("rPr", "pPr", "tcPr"):
            props = node.find(_W + tag)
            if props is not None and _shaded(props):
                return True
        node = node.getparent()
    return False


def docx_run_is_hidden(run) -> bool:
    """True for a Word run a reader cannot see: marked hidden, 1-point text, or white text on a white background.
    White text on a shaded banner (the way our own resumes print their section headings) is visible and is kept."""
    try:
        font = run.font
        if font.hidden:
            return True
        if font.size is not None and font.size.pt <= 2:
            return True
        color = font.color
        if color is not None and color.rgb is not None and str(color.rgb).upper() in ("FFFFFF", "FFFFFE"):
            return not _formatting_shaded(run._r)
    except Exception:
        return False
    return False
