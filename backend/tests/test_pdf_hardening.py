"""PDF reading: pinned to a patched pypdf, still reads real resumes, and handles bad files in a controlled way.

Why this file exists: pypdf 6.19.0 had 18 published security advisories (infinite loops, long runtimes and large memory use on
crafted files; fixed in 6.21.4). These tests keep the pin from slipping back and check how our own reader behaves.

Safety rule for this file: anything that feeds a hostile or malformed file to the parser runs in a SEPARATE PROCESS with a hard
external timeout (and, where the system supports it, a memory limit), so a parser that hangs or balloons fails one test quickly
instead of freezing or crashing the whole test run. Only well-formed, bounded files are read in-process.

Run from the backend folder:  py -3.12 -m unittest discover -s tests -t .
"""
import io
import json
import os
import re
import subprocess
import sys
import unittest
import zlib
from unittest import mock

from fastapi.testclient import TestClient
from pypdf import PdfWriter

import abuse_guard
import extractor
import main
from tests.test_ownership import OwnershipTestCase

BACKEND = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
REQUIREMENTS = os.path.join(BACKEND, "requirements.txt")
MIN_SAFE_PYPDF = (6, 21, 4)  # the first release with no published advisory affecting how we use pypdf (checked 2026-11-01)

ISOLATED_TIMEOUT_SECONDS = 25
ISOLATED_MEMORY_MB = 2048  # address-space cap for the child; only enforced where the OS supports it (Linux, i.e. CI)

# The child process: reads the file from stdin, runs our real extractor, prints ONE json line. Never raises to the parent.
CHILD = r"""
import json, sys
sys.path.insert(0, sys.argv[1])
try:
    import resource
    limit = int(sys.argv[2]) * 1024 * 1024
    resource.setrlimit(resource.RLIMIT_AS, (limit, limit))
except Exception:
    pass
import extractor
data = sys.stdin.buffer.read()
try:
    text = extractor.extract_text("upload.pdf", data)
    print(json.dumps({"outcome": "text", "chars": len(text), "text": text[:300]}))
except ValueError as e:
    print(json.dumps({"outcome": "refused", "message": str(e)}))
except BaseException as e:
    print(json.dumps({"outcome": "crash", "error": type(e).__name__}))
"""


def parse_isolated(data: bytes, timeout: int = ISOLATED_TIMEOUT_SECONDS) -> dict:
    """Read `data` as an uploaded PDF in a child process. The parent enforces the deadline and kills a child that overruns it."""
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    try:
        done = subprocess.run(
            [sys.executable, "-c", CHILD, BACKEND, str(ISOLATED_MEMORY_MB)],
            input=data, capture_output=True, timeout=timeout, env=env, cwd=BACKEND,
        )
    except subprocess.TimeoutExpired:
        return {"outcome": "timeout"}
    lines = done.stdout.decode("utf-8", "replace").strip().splitlines()
    if not lines:
        # killed by the memory limit or the OS before it could report: treated as "the parser did not cope", not as a hang
        return {"outcome": "died", "returncode": done.returncode, "stderr": done.stderr.decode("utf-8", "replace")[-300:]}
    return json.loads(lines[-1])


# ---- building small PDFs by hand (no binary fixtures in the repo) -------------------------------------------------------

def assemble(objects, trailer_extra=b"", header=b"%PDF-1.7\n"):
    """objects: list of bytes bodies for objects 1..n. Object 1 must be the catalog. Returns a well-formed file with a real xref table."""
    out = bytearray(header)
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % number + body + b"\nendobj\n"
    xref_at = len(out)
    out += b"xref\n0 %d\n" % (len(objects) + 1)
    out += b"0000000000 65535 f \n"
    for off in offsets:
        out += b"%010d 00000 n \n" % off
    out += b"trailer\n<< /Size %d /Root 1 0 R %s>>\nstartxref\n%d\n%%%%EOF\n" % (len(objects) + 1, trailer_extra, xref_at)
    return bytes(out)


def stream(dictionary: bytes, payload: bytes) -> bytes:
    return b"<< " + dictionary + b" /Length %d >>\nstream\n" % len(payload) + payload + b"\nendstream"


def pdf_escape(raw: bytes) -> bytes:
    return raw.replace(b"\\", b"\\\\").replace(b"(", b"\\(").replace(b")", b"\\)")


def winansi_pdf(lines):
    """One page, standard Helvetica with WinAnsi encoding. `lines` are bytes in Windows-1252 (so accents, curly quotes and dashes are real)."""
    content = b"BT /F1 12 Tf 72 720 Td 16 TL\n" + b"".join(b"(" + pdf_escape(line) + b") '\n" for line in lines) + b"ET"
    return assemble([
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
        stream(b"", content),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
    ])


def unicode_pdf(text: str):
    """One page whose font maps two-byte codes to Unicode through a /ToUnicode table, the way most non-Latin resumes are stored."""
    chars = sorted(set(text) - {"\n"})
    codes = {ch: i + 1 for i, ch in enumerate(chars)}
    bfchar = b"".join(b"<%04X> <%s>\n" % (code, ch.encode("utf-16-be").hex().upper().encode()) for ch, code in codes.items())
    cmap = (b"/CIDInit /ProcSet findresource begin 12 dict begin begincmap\n"
            b"/CMapName /Adobe-Identity-UCS def /CMapType 2 def\n"
            b"1 begincodespacerange <0000> <FFFF> endcodespacerange\n"
            b"%d beginbfchar\n" % len(codes) + bfchar + b"endbfchar\nendcmap CMapName currentdict /CMap defineresource pop end end")
    shown = b"".join(b"<" + b"".join(b"%04X" % codes[ch] for ch in line) + b"> Tj T*\n" for line in text.split("\n"))
    content = b"BT /F1 12 Tf 72 720 Td 16 TL\n" + shown + b"ET"
    return assemble([
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
        stream(b"", content),
        b"<< /Type /Font /Subtype /Type0 /BaseFont /Sample /Encoding /Identity-H /DescendantFonts [6 0 R] /ToUnicode 7 0 R >>",
        b"<< /Type /Font /Subtype /CIDFontType2 /BaseFont /Sample /CIDSystemInfo << /Registry (Adobe) /Ordering (Identity) /Supplement 0 >> /DW 600 >>",
        stream(b"", cmap),
    ])


def blank_pages_pdf(pages):
    w = PdfWriter()
    for _ in range(pages):
        w.add_blank_page(width=200, height=200)
    buf = io.BytesIO()
    w.write(buf)
    return buf.getvalue()


# ---- 1. the pin ----------------------------------------------------------------------------------------------------

def _version(text):
    return tuple(int(x) for x in re.findall(r"\d+", text)[:3])


class PinnedVersion(unittest.TestCase):
    def pinned(self):
        with open(REQUIREMENTS, encoding="utf-8") as f:
            match = re.search(r"^pypdf==([\d.]+)\s*$", f.read(), re.M)
        self.assertIsNotNone(match, "requirements.txt must pin pypdf exactly (pypdf==X.Y.Z)")
        return match.group(1)

    def test_the_pin_is_not_older_than_the_first_patched_release(self):
        self.assertGreaterEqual(_version(self.pinned()), MIN_SAFE_PYPDF,
                                "pypdf is pinned below the first release without published advisories; see this file's docstring")

    @unittest.skipUnless(os.environ.get("CI") == "true", "only checked where the libraries are installed from the pins (GitHub CI)")
    def test_the_installed_pypdf_is_the_pinned_one(self):
        import pypdf
        self.assertEqual(pypdf.__version__, self.pinned())


# ---- 2. normal files still read exactly as before -----------------------------------------------------------------

class NormalExtraction(unittest.TestCase):
    def test_a_plain_one_page_resume_is_read(self):
        text = extractor.extract_text("resume.pdf", winansi_pdf([b"Jane Doe", b"Cashier, Corner Store, 2019 - 2024", b"Handled cash and helped customers."]))
        self.assertEqual(text.splitlines(), ["Jane Doe", "Cashier, Corner Store, 2019 - 2024", "Handled cash and helped customers."])

    def test_accented_names_and_punctuation_survive(self):
        # Windows-1252 bytes: 0x93/0x94 curly quotes, 0x92 apostrophe, 0x96 en dash, 0x97 em dash, 0x95 bullet
        lines = ["José Peña — Zoë Müller", "“Quoted” and it’s fine – really", "• Bilingual: español, français, português"]
        text = extractor.extract_text("resume.pdf", winansi_pdf([line.encode("cp1252") for line in lines]))
        # extractor.extract_text runs ftfy.fix_text, which has always turned curly quotes into straight ones; that is existing behavior to preserve
        expected = ["José Peña — Zoë Müller", "\"Quoted\" and it's fine – really", "• Bilingual: español, français, português"]
        self.assertEqual(text.splitlines(), expected)

    def test_non_latin_names_come_through_a_unicode_font_map(self):
        text = extractor.extract_text("resume.pdf", unicode_pdf("李明\nΕλένη Παπαδοπούλου\nПривет мир"))
        self.assertEqual(text.splitlines(), ["李明", "Ελένη Παπαδοπούλου", "Привет мир"])

    def test_the_file_name_case_does_not_matter(self):
        self.assertIn("Jane", extractor.extract_text("RESUME.PDF", winansi_pdf([b"Jane Doe"])))

    def test_a_page_with_no_text_reads_as_empty_not_as_an_error(self):
        self.assertEqual(extractor.extract_text("scan.pdf", blank_pages_pdf(1)), "")


# ---- 3. page-count and size limits stay as they were ------------------------------------------------------------

class PageLimit(unittest.TestCase):
    def test_exactly_the_maximum_pages_is_accepted_and_one_more_is_refused(self):
        self.assertEqual(extractor.extract_text("a.pdf", blank_pages_pdf(extractor.MAX_PDF_PAGES)), "")
        with self.assertRaises(ValueError) as caught:
            extractor.extract_text("a.pdf", blank_pages_pdf(extractor.MAX_PDF_PAGES + 1))
        self.assertIn("too many pages", str(caught.exception))

    def test_the_limits_themselves_have_not_been_loosened(self):
        self.assertEqual(extractor.MAX_PDF_PAGES, 150)
        self.assertEqual(extractor.EXTRACT_TIMEOUT_SECONDS, 30)


class SizeLimits(OwnershipTestCase):
    """Signed-in upload (/resume-start): 20 MB for a PDF, 5 MB for anything else. The AI and the reader are replaced, so this tests only the gate."""
    MB = 1024 * 1024

    def setUp(self):
        super().setUp()
        import abuse_guard as guard
        for patcher in (
            mock.patch.dict(os.environ, {"RATE_LIMIT_USER": "1000/60"}),
            mock.patch.object(guard, "LIMITER", guard.SlidingWindowLimiter()),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        guard.IN_FLIGHT.reset()
        self.onboard(self.a)

    def upload(self, name, size):
        with mock.patch("career.routes.extract_text_async", return_value="Jane Doe, cashier.") as reader, \
                mock.patch("career.routes.start_resume_review", return_value={"roles": [], "education": [], "certifications": [], "categories": [], "questions": [], "analysis_summary": ""}):
            res = self.call("POST", "/resume-start", self.a, files={"resume_file": (name, b"x" * size, "application/octet-stream")})
        return res, reader

    def test_a_pdf_may_be_up_to_20_mb(self):
        res, reader = self.upload("resume.pdf", 20 * self.MB)
        self.assertEqual(res.status_code, 200, res.text)
        reader.assert_called_once()

    def test_a_pdf_over_20_mb_is_refused_before_it_is_read(self):
        res, reader = self.upload("resume.pdf", 20 * self.MB + 1)
        self.assertEqual(res.status_code, 413, res.text)
        reader.assert_not_called()

    def test_other_files_over_5_mb_are_refused_before_they_are_read(self):
        for name in ("resume.docx", "resume.txt"):
            with self.subTest(name=name):
                res, reader = self.upload(name, 5 * self.MB + 1)
                self.assertEqual(res.status_code, 413, res.text)
                reader.assert_not_called()


class PublicToolSizeLimits(unittest.TestCase):
    MB = 1024 * 1024

    def setUp(self):
        abuse_guard.reset()
        self.addCleanup(abuse_guard.reset)
        patcher = mock.patch("turnstile.enabled", return_value=False)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.client = TestClient(main.app)

    def analyze(self, size):
        with mock.patch.object(main, "extract_text_async", return_value="Jane Doe, cashier.") as reader, \
                mock.patch.object(main, "analyze", return_value={"ok": True}):
            res = self.client.post("/api/analyze", files={"resume_file": ("resume.pdf", b"x" * size, "application/pdf")},
                                   data={"job_posting": "Customer service associate wanted. Requires cash handling and teamwork in retail."})
        return res, reader

    def test_a_public_tool_resume_over_5_mb_is_refused_before_it_is_read(self):
        res, reader = self.analyze(5 * self.MB + 1)
        self.assertEqual(res.status_code, 413, res.text)
        reader.assert_not_called()
        abuse_guard.reset()
        res, reader = self.analyze(5 * self.MB)
        self.assertEqual(res.status_code, 200, res.text)
        reader.assert_called_once()

    def test_a_profile_pdf_over_20_mb_is_refused_before_it_is_read(self):
        with mock.patch.object(main, "extract_text_async", return_value="x") as reader:
            res = self.client.post("/api/profile-review", files={"profile_pdf": ("profile.pdf", b"x" * (20 * self.MB + 1), "application/pdf")}, data={"everything": "hello"})
        self.assertEqual(res.status_code, 413, res.text)
        reader.assert_not_called()


# ---- 4. bad files are handled in a controlled way (each one in its own process, with a hard deadline) ----------------

def encrypted_pdf():
    w = PdfWriter()
    w.add_blank_page(width=200, height=200)
    w.encrypt("owner-and-user-password", algorithm="AES-256")
    buf = io.BytesIO()
    w.write(buf)
    return buf.getvalue()


def circular_prev_pdf():
    """A well-formed file whose trailer points back to its own cross-reference table."""
    base = winansi_pdf([b"Jane Doe"])
    xref_at = int(re.search(rb"startxref\n(\d+)", base).group(1))
    return base.replace(b"/Root 1 0 R ", b"/Root 1 0 R /Prev %d " % xref_at)


def missing_object_flood_pdf():
    refs = b" ".join([b"9 0 R"] * 60000)  # 60,000 references to an object that does not exist
    return assemble([
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents [" + refs + b"] /Resources << >> >>",
    ])


def huge_xref_header_pdf():
    return b"%PDF-1.7\n1 0 obj\n<< /Type /Catalog >>\nendobj\nxref\n0 999999999999\n0000000000 65535 f \ntrailer\n<< /Size 999999999999 /Root 1 0 R >>\nstartxref\n40\n%%EOF\n"


def lying_stream_length_pdf():
    return assemble([
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << >> >>",
        b"<< /Length 2000000000 >>\nstream\nBT ET\nendstream",
    ])


def flate_expansion_pdf(megabytes):
    """A real, valid page whose content stream is a few KB packed but `megabytes` MB once unpacked."""
    packed = zlib.compress(b" " * (megabytes * 1024 * 1024) + b"\nBT ET", 9)
    return assemble([
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << >> >>",
        stream(b"/Filter /FlateDecode", packed),
    ])


def deeply_nested_pdf():
    return assemble([
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << >> /Junk " + b"[" * 200000 + b" >>",
    ])


MALFORMED = {
    "empty file": b"",
    "plain text renamed to .pdf": b"This is not a PDF at all.\n" * 50,
    "header only": b"%PDF-1.7\n",
    "random bytes after the header": b"%PDF-1.7\n" + bytes(range(256)) * 40,
    "valid file cut in half": winansi_pdf([b"Jane Doe"] * 5)[:300],
    "cross-reference table cut off at end of file": b"%PDF-1.7\n1 0 obj\n<< /Type /Catalog >>\nendobj\nxref\n0 5\n0000000000 65535 f \n",
    "trailer points back to itself (circular /Prev)": circular_prev_pdf(),
    "enormous cross-reference size": huge_xref_header_pdf(),
    "tens of thousands of references to a missing object": missing_object_flood_pdf(),
    "stream length claims two gigabytes": lying_stream_length_pdf(),
    "extremely deep nesting": deeply_nested_pdf(),
    "unknown password (encrypted)": encrypted_pdf(),
    "40 MB of data packed into a few KB (compression bomb)": flate_expansion_pdf(40),
}


class MalformedFiles(unittest.TestCase):
    def test_every_bad_file_finishes_inside_the_deadline_and_ends_in_a_controlled_result(self):
        for label, data in MALFORMED.items():
            with self.subTest(file=label):
                result = parse_isolated(data)
                self.assertNotEqual(result["outcome"], "timeout", f"{label}: the reader did not finish within {ISOLATED_TIMEOUT_SECONDS} s (the child was killed)")
                self.assertNotEqual(result["outcome"], "crash", f"{label}: an unexpected error escaped the extractor ({result})")
                self.assertIn(result["outcome"], ("refused", "text", "died"), result)

    def test_files_that_cannot_be_files_are_refused_with_the_friendly_message(self):
        for label in ("empty file", "plain text renamed to .pdf", "header only", "random bytes after the header", "unknown password (encrypted)"):
            with self.subTest(file=label):
                result = parse_isolated(MALFORMED[label])
                self.assertEqual(result["outcome"], "refused", result)
                self.assertIn("Could not read that .pdf file", result["message"])

    def test_a_normal_file_still_reads_when_run_the_same_isolated_way(self):
        result = parse_isolated(winansi_pdf([b"Jane Doe", b"Cashier"]))
        self.assertEqual(result["outcome"], "text", result)
        self.assertEqual(result["text"].splitlines(), ["Jane Doe", "Cashier"])

    def test_the_harness_really_does_kill_a_child_that_overruns_its_deadline(self):
        """Proves the safety net itself: a child that never finishes is reported as a timeout, quickly, and the test run is not blocked."""
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
        with self.assertRaises(subprocess.TimeoutExpired):
            subprocess.run([sys.executable, "-c", "import time\nwhile True: time.sleep(0.1)"], timeout=2, env=env)


if __name__ == "__main__":
    unittest.main()
