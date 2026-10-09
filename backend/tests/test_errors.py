"""Internal errors give a safe message and a reference, never the exception's own text (risk-audit finding F-08)."""
import contextlib
import io
import os
import re
import unittest
from unittest import mock

from fastapi.testclient import TestClient

import abuse_guard
import main
from errors import internal_error

BACKEND = os.path.join(os.path.dirname(__file__), "..")
SECRET = "SECRET-PATH-C:\\\\srv\\\\app\\\\private.py line 99"


class InternalErrorTests(unittest.TestCase):
    def test_the_visitor_sees_a_reference_and_no_details(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            err = internal_error(RuntimeError(SECRET), "resume build")
        self.assertEqual(err.status_code, 500)
        self.assertNotIn("SECRET", err.detail)
        self.assertNotIn("RuntimeError", err.detail)
        ref = re.search(r"reference ([0-9a-f]{6})", err.detail).group(1)
        self.assertIn(f"ref={ref}", out.getvalue(), "the same reference is in the server log")

    def test_the_log_has_the_kind_of_error_but_never_its_message(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            internal_error(ValueError(SECRET), "x")
        self.assertIn("class=ValueError", out.getvalue())
        self.assertNotIn("SECRET", out.getvalue())

    def test_references_differ_between_errors(self):
        with contextlib.redirect_stdout(io.StringIO()):
            refs = {re.search(r"reference (\w+)", internal_error(RuntimeError()).detail).group(1) for _ in range(20)}
        self.assertGreater(len(refs), 15)


class RouteBehaviourTests(unittest.TestCase):
    def setUp(self):
        abuse_guard.reset()
        self.client = TestClient(main.app, raise_server_exceptions=False)

    def test_a_crash_inside_a_tool_does_not_leak_its_message(self):
        with mock.patch.object(main, "analyze", side_effect=RuntimeError(SECRET)), contextlib.redirect_stdout(io.StringIO()):
            res = self.client.post("/api/analyze", files={"resume_file": ("r.txt", b"Ada Lovelace, engineer")}, data={"job_posting": "x" * 60})
        self.assertEqual(res.status_code, 500)
        self.assertNotIn("SECRET", res.text)
        self.assertIn("reference", res.json()["detail"])

    def test_a_crash_while_building_a_document_does_not_leak_its_message(self):
        with mock.patch.object(main, "build_resume_bytes", side_effect=RuntimeError(SECRET)), contextlib.redirect_stdout(io.StringIO()):
            res = self.client.post("/api/generate", json={"resume_data": {"name": "A", "contact": "c", "skills": [], "experience": [], "education": []}})
        self.assertEqual(res.status_code, 500)
        self.assertNotIn("SECRET", res.text)

    def test_the_tools_own_friendly_messages_are_still_passed_on(self):
        res = self.client.post("/api/refine", files={"resume_file": ("r.txt", b"")})
        self.assertEqual(res.status_code, 400)
        self.assertIn("Could not extract any text", res.json()["detail"])


class NoLeakGuardTests(unittest.TestCase):
    def test_no_route_puts_an_exceptions_text_in_a_500_answer(self):
        for rel in ("main.py", os.path.join("career", "routes.py")):
            with open(os.path.join(BACKEND, rel), encoding="utf-8") as fh:
                src = fh.read()
            self.assertNotIn("Unexpected error", src, rel)
            self.assertNotRegex(src, r"status_code=500, detail=f?\"[^\"]*\{e", rel)
            self.assertNotRegex(src, r"Failed to build[^\"]*\{e\}", rel)


if __name__ == "__main__":
    unittest.main()
