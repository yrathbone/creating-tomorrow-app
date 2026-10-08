"""Runs the Node test for the resume-header prefill (backend/tests/frontend/profile_basics.test.js)
as part of the normal `unittest discover`. Skipped, not failed, when Node is not installed."""
import shutil
import subprocess
import unittest
from pathlib import Path


@unittest.skipUnless(shutil.which("node"), "Node.js is not installed")
class FrontendProfileBasics(unittest.TestCase):
    def test_profile_basics_prefill(self):
        test_file = Path(__file__).parent / "frontend" / "profile_basics.test.js"
        result = subprocess.run(["node", "--test", str(test_file)], capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
