"""Reading uploaded files must not freeze the server or be tricked by decompression bombs (risk-audit finding F-05)."""
import asyncio
import io
import threading
import time
import unittest
from unittest import mock

from docx import Document
from fastapi.testclient import TestClient
from pypdf import PdfWriter

import abuse_guard
import extractor
import main


def docx_bytes(text="Ada Lovelace\nAnalytical engines"):
    doc = Document()
    for line in text.split("\n"):
        doc.add_paragraph(line)
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def pdf_bytes(pages):
    w = PdfWriter()
    for _ in range(pages):
        w.add_blank_page(width=200, height=200)
    buf = io.BytesIO()
    w.write(buf)
    return buf.getvalue()


class SafetyTests(unittest.TestCase):
    def test_normal_files_still_read(self):
        self.assertIn("Ada Lovelace", extractor.extract_text("r.docx", docx_bytes()))
        self.assertEqual(extractor.extract_text("r.pdf", pdf_bytes(3)), "")
        self.assertEqual(extractor.extract_text("r.txt", "héllo".encode()), "héllo")

    def test_a_word_file_that_unpacks_to_too_much_is_refused(self):
        with mock.patch.object(extractor, "MAX_DOCX_UNPACKED_BYTES", 500):
            with self.assertRaisesRegex(ValueError, "too large or complex"):
                extractor.extract_text("r.docx", docx_bytes())

    def test_a_real_zip_bomb_is_caught_without_unpacking_it(self):
        import zipfile
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("word/document.xml", b"\0" * (120 * 1024 * 1024))     # compresses to about 120 KB
        self.assertLess(len(buf.getvalue()), 1024 * 1024)
        started = time.time()
        with self.assertRaisesRegex(ValueError, "too large or complex"):
            extractor.extract_text("bomb.docx", buf.getvalue())
        self.assertLess(time.time() - started, 5)

    def test_a_word_file_with_thousands_of_parts_is_refused(self):
        with mock.patch.object(extractor, "MAX_DOCX_ENTRIES", 3):
            with self.assertRaisesRegex(ValueError, "too large or complex"):
                extractor.extract_text("r.docx", docx_bytes())

    def test_a_pdf_with_too_many_pages_is_refused(self):
        with mock.patch.object(extractor, "MAX_PDF_PAGES", 2):
            with self.assertRaisesRegex(ValueError, "too many pages"):
                extractor.extract_text("r.pdf", pdf_bytes(3))
            extractor.extract_text("r.pdf", pdf_bytes(2))

    def test_a_file_that_is_not_what_its_name_says_is_a_friendly_error(self):
        with self.assertRaisesRegex(ValueError, "Could not read that .docx file"):
            extractor.extract_text("r.docx", b"not a zip at all")


class OffTheMainLoopTests(unittest.TestCase):
    def test_reading_runs_on_a_worker_thread_not_the_event_loop(self):
        seen = {}

        def spy(filename, content):
            seen["thread"] = threading.get_ident()
            return "text"

        async def run():
            seen["loop_thread"] = threading.get_ident()
            return await extractor.extract_text_async("r.txt", b"x")

        with mock.patch.object(extractor, "extract_text", spy):
            self.assertEqual(asyncio.run(run()), "text")
        self.assertNotEqual(seen["thread"], seen["loop_thread"])

    def test_the_event_loop_stays_free_while_a_slow_file_is_read(self):
        def slow(filename, content):
            time.sleep(0.4)
            return "slow text"

        async def run():
            ticks = 0

            async def ticker():
                nonlocal ticks
                while True:
                    await asyncio.sleep(0.02)
                    ticks += 1

            t = asyncio.create_task(ticker())
            result = await extractor.extract_text_async("r.txt", b"x")
            t.cancel()
            return result, ticks

        with mock.patch.object(extractor, "extract_text", slow):
            result, ticks = asyncio.run(run())
        self.assertEqual(result, "slow text")
        self.assertGreater(ticks, 8, "other requests kept being served while the file was read")

    def test_a_file_that_takes_too_long_gets_a_friendly_error(self):
        def stuck(filename, content):
            time.sleep(0.5)
            return "late"

        with mock.patch.object(extractor, "extract_text", stuck), mock.patch.object(extractor, "EXTRACT_TIMEOUT_SECONDS", 0.05):
            with self.assertRaisesRegex(ValueError, "took too long"):
                asyncio.run(extractor.extract_text_async("r.txt", b"x"))


class RouteTests(unittest.TestCase):
    def setUp(self):
        abuse_guard.reset()
        self.client = TestClient(main.app, raise_server_exceptions=False)

    def test_a_bomb_uploaded_to_a_real_tool_gets_a_friendly_400(self):
        with mock.patch.object(extractor, "MAX_DOCX_UNPACKED_BYTES", 500):
            res = self.client.post("/api/refine", files={"resume_file": ("r.docx", docx_bytes())})
        self.assertEqual(res.status_code, 400)
        self.assertIn("too large or complex", res.json()["detail"])

    def test_a_normal_text_file_still_reaches_the_tool(self):
        with mock.patch.object(main, "upgrade", side_effect=main.UpgradeError("tool says hi")):
            res = self.client.post("/api/refine", files={"resume_file": ("r.txt", b"Ada Lovelace, engineer")})
        self.assertEqual(res.status_code, 502)
        self.assertEqual(res.json()["detail"], "tool says hi")


if __name__ == "__main__":
    unittest.main()
