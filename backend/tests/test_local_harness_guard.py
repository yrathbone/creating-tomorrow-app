"""The local signed-in harness refuses to run anywhere but a developer's localhost (C-52 F08). Offline."""
import os
import pathlib
import sys
import unittest
from unittest import mock

HARNESS = pathlib.Path(__file__).resolve().parent / "harness"
sys.path.insert(0, str(HARNESS))

import local_signed_in as harness  # noqa: E402


class HarnessGuard(unittest.TestCase):
    def _env(self, **extra):
        base = {"CT_LOCAL_HARNESS": "1"}
        base.update(extra)
        return mock.patch.dict(os.environ, base, clear=True)

    def test_refused_without_the_explicit_flag(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(SystemExit):
                harness.guard("127.0.0.1")

    def test_refused_on_any_host_other_than_loopback(self):
        with self._env():
            for host in ("0.0.0.0", "localhost", "192.168.1.5"):
                with self.subTest(host=host), self.assertRaises(SystemExit):
                    harness.guard(host)

    def test_refused_when_a_hosting_platform_marker_is_present(self):
        for marker in ("RENDER", "RENDER_SERVICE_ID", "RENDER_EXTERNAL_URL"):
            with self.subTest(marker=marker), self._env(**{marker: "1"}), self.assertRaises(SystemExit):
                harness.guard("127.0.0.1")

    def test_refused_when_the_environment_is_production(self):
        with self._env(CT_ENV="production"), self.assertRaises(SystemExit):
            harness.guard("127.0.0.1")

    def test_allowed_only_on_loopback_with_the_flag_and_no_platform_marker(self):
        with self._env():
            harness.guard("127.0.0.1")   # does not raise

    def test_the_harness_uses_no_committed_key_and_no_cognito_network_identifier(self):
        src = (HARNESS / "local_signed_in.py").read_text(encoding="utf-8")
        self.assertNotIn("BEGIN PRIVATE KEY", src)
        self.assertNotIn("BEGIN RSA", src)
        self.assertIn('POOL = "us-east-2_LOCALHARNESS"', src)
        self.assertIn("generate_private_key", src)


if __name__ == "__main__":
    unittest.main()
