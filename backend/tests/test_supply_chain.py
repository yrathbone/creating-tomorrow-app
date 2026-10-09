"""Exact library versions, automatic tests on every push, and automatic update alerts (risk-audit findings F-13 and F-17)."""
import os
import re
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


def read(*parts):
    with open(os.path.join(ROOT, *parts), encoding="utf-8") as fh:
        return fh.read()


class PinnedLibraries(unittest.TestCase):
    def lines(self):
        return [l.strip() for l in read("backend", "requirements.txt").splitlines() if l.strip() and not l.strip().startswith("#")]

    def test_every_library_is_pinned_to_one_exact_version(self):
        for line in self.lines():
            self.assertRegex(line, r"^[A-Za-z0-9_.\-]+(\[[a-z,]+\])?==\d+(\.\d+)*$", f"not an exact pin: {line}")

    def test_the_libraries_the_site_imports_are_all_listed(self):
        names = {re.split(r"[\[=]", l)[0].lower() for l in self.lines()}
        for needed in ("fastapi", "uvicorn", "python-multipart", "python-docx", "pypdf", "ftfy", "anthropic", "pydantic", "sqlalchemy", "alembic", "psycopg", "python-jose"):
            self.assertIn(needed, names)

    def test_no_pin_uses_a_range_or_a_wildcard(self):
        text = "\n".join(self.lines())
        for bad in (">=", "<=", "~=", "*", ">", "<"):
            self.assertNotIn(bad, text)


class AutomaticTests(unittest.TestCase):
    def test_the_workflow_runs_both_suites_on_every_push_and_pull_request(self):
        wf = read(".github", "workflows", "tests.yml")
        self.assertIn("push:", wf)
        self.assertIn("pull_request:", wf)
        self.assertIn("python -m unittest discover -s tests -t .", wf)
        self.assertIn("node --test backend/tests/frontend/*.test.js", wf)
        self.assertIn("pip install -r backend/requirements-dev.txt", wf)
        self.assertIn("-r requirements.txt", read("backend", "requirements-dev.txt"), "the tests run against the same pinned libraries as the live site")
        self.assertIn("contents: read", wf, "the workflow gets read-only access")

    def test_both_python_versions_are_tested(self):
        wf = read(".github", "workflows", "tests.yml")
        self.assertIn('"3.12"', wf)
        self.assertIn('"3.14"', wf)

    def test_the_actions_it_uses_are_pinned_to_a_major_version(self):
        for use in re.findall(r"uses:\s*(\S+)", read(".github", "workflows", "tests.yml")):
            self.assertRegex(use, r"@v\d+$", use)

    def test_dependabot_watches_the_libraries_and_the_actions(self):
        d = read(".github", "dependabot.yml")
        self.assertIn('package-ecosystem: "pip"', d)
        self.assertIn('directory: "/backend"', d)
        self.assertIn('package-ecosystem: "github-actions"', d)


if __name__ == "__main__":
    unittest.main()
