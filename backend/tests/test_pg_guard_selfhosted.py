"""Refusal tests for the self-hosted PostgreSQL test mode (C-52). Offline: no database is contacted.

Every test points CT_TEST_POSTGRES_ENV_FILE at a file that does not exist, so the founder's local file is never read."""
import os
import pathlib
import sys
import tempfile
import unittest
from unittest import mock

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BACKEND, "tests", "harness"))
import pg_test_config as cfgmod  # noqa: E402

HOST = "ct-c52-test.internal.example"
GOOD = {
    "CT_TEST_HOST_MODE": "selfhosted",
    "CT_TEST_SELFHOSTED_HOST": HOST,
    "CT_TEST_POSTGRES_DB": "ct_c52_test",
    "CT_TEST_POSTGRES_URL": f"postgresql://ct_c52_runner:synthetic-only@{HOST}:5432/ct_c52_test?sslmode=require",
    "CT_TEST_DISPOSABLE_CONFIRMED": "yes",
    "CT_TEST_PG_MAJOR": "16",
}


def _load(overrides=None, drop=()):
    env = dict(GOOD, **(overrides or {}))
    for k in drop:
        env.pop(k, None)
    missing_file = str(pathlib.Path(tempfile.gettempdir()) / "c52-does-not-exist.env")
    with mock.patch.dict(os.environ, dict(env, CT_TEST_POSTGRES_ENV_FILE=missing_file), clear=True):
        return cfgmod.load()


class SelfHostedMode(unittest.TestCase):
    def assertRefused(self, **kw):
        with self.assertRaises(cfgmod.ConfigError) as ctx:
            _load(**kw)
        return str(ctx.exception)

    def test_accepts_the_exact_configured_test_host_and_database(self):
        cfg = _load()
        self.assertEqual(cfg["database"], "ct_c52_test")
        self.assertEqual(cfg["endpoint"], HOST)
        self.assertEqual(cfg["major"], 16)

    def test_refuses_without_the_disposable_confirmation(self):
        self.assertRefused(overrides={"CT_TEST_DISPOSABLE_CONFIRMED": "no"})
        self.assertRefused(drop=("CT_TEST_DISPOSABLE_CONFIRMED",))

    def test_refuses_a_different_host_even_if_it_shares_a_suffix(self):
        self.assertRefused(overrides={"CT_TEST_POSTGRES_URL": f"postgresql://u:p@evil.{HOST}:5432/ct_c52_test?sslmode=require"})
        self.assertRefused(overrides={"CT_TEST_POSTGRES_URL": f"postgresql://u:p@{HOST}.attacker.example:5432/ct_c52_test?sslmode=require"})

    def test_refuses_when_the_configured_host_is_missing(self):
        self.assertRefused(drop=("CT_TEST_SELFHOSTED_HOST",))

    def test_refuses_without_tls(self):
        self.assertRefused(overrides={"CT_TEST_POSTGRES_URL": f"postgresql://u:p@{HOST}:5432/ct_c52_test"})
        self.assertRefused(overrides={"CT_TEST_POSTGRES_URL": f"postgresql://u:p@{HOST}:5432/ct_c52_test?sslmode=disable"})

    def test_refuses_a_production_looking_host_or_database(self):
        self.assertRefused(overrides={"CT_TEST_SELFHOSTED_HOST": "prod-db.internal.example",
                                      "CT_TEST_POSTGRES_URL": "postgresql://u:p@prod-db.internal.example:5432/ct_c52_test?sslmode=require"})
        self.assertRefused(overrides={"CT_TEST_POSTGRES_DB": "ct_c52_production", "CT_TEST_POSTGRES_URL": f"postgresql://u:p@{HOST}:5432/ct_c52_production?sslmode=require"})

    def test_refuses_a_database_name_not_marked_as_the_c52_test_database(self):
        self.assertRefused(overrides={"CT_TEST_POSTGRES_DB": "creating_tomorrow", "CT_TEST_POSTGRES_URL": f"postgresql://u:p@{HOST}:5432/creating_tomorrow?sslmode=require"})
        self.assertRefused(overrides={"CT_TEST_POSTGRES_DB": "postgres", "CT_TEST_POSTGRES_URL": f"postgresql://u:p@{HOST}:5432/postgres?sslmode=require"})

    def test_refuses_a_database_in_the_url_that_differs_from_the_expected_one(self):
        self.assertRefused(overrides={"CT_TEST_POSTGRES_URL": f"postgresql://u:p@{HOST}:5432/ct_c52_other?sslmode=require"})

    def test_refuses_a_render_host(self):
        self.assertRefused(overrides={"CT_TEST_SELFHOSTED_HOST": "ct-app.onrender.com",
                                      "CT_TEST_POSTGRES_URL": "postgresql://u:p@ct-app.onrender.com:5432/ct_c52_test?sslmode=require"})

    def test_refuses_a_non_postgres_url(self):
        self.assertRefused(overrides={"CT_TEST_POSTGRES_URL": f"mysql://u:p@{HOST}:3306/ct_c52_test?sslmode=require"})

    def test_mode_is_opt_in_only(self):
        # The mode must be set explicitly; without it the configuration is refused.
        self.assertRefused(drop=("CT_TEST_HOST_MODE",))
        self.assertRefused(overrides={"CT_TEST_HOST_MODE": "other"})


if __name__ == "__main__":
    unittest.main()
