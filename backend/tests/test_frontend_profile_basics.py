"""Runs the Node tests for the frontend pieces (backend/tests/frontend/*.test.js: resume-header
prefill, My Career card) as part of the normal `unittest discover`. Skipped, not failed, when Node is not installed."""
import shutil
import subprocess
import unittest
from pathlib import Path


@unittest.skipUnless(shutil.which("node"), "Node.js is not installed")
class FrontendNodeTests(unittest.TestCase):
    def test_frontend_node_tests(self):
        files = sorted(str(p) for p in (Path(__file__).parent / "frontend").glob("*.test.js"))
        self.assertTrue(files, "no Node test files found")
        result = subprocess.run(["node", "--test", *files], capture_output=True, text=True, timeout=120)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
