"""N-06 safety checks for the browser-test server (e2e/server/run_test_server.py). These run in the normal Python suite, need no browser and
touch no network: they prove the launcher can only ever point at local fakes, and that the tokens it mints work through the REAL token check
(and only for the planted key), so the browser tests cannot reach the production database, the Cognito tenant or the Anthropic API."""
import importlib.util
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import auth.dependencies as deps
from career.routes import router
from db import Base, get_db_session

LAUNCHER = Path(__file__).resolve().parents[2] / "e2e" / "server" / "run_test_server.py"


def load_launcher():
    spec = importlib.util.spec_from_file_location("run_test_server", LAUNCHER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


REAL_ENV = {  # what a developer's shell or the Render environment could contain (all fictional values; none are real secrets)
    "PATH": "/usr/bin",
    "DATABASE_URL": "postgresql://user:pw@dpg-xyz.oregon-postgres.render.com/creating_tomorrow",
    "ANTHROPIC_API_KEY": "sk-ant-fictional-value",
    "ANTHROPIC_BASE_URL": "https://api.anthropic.com",
    "COGNITO_REGION": "us-east-2",
    "COGNITO_USER_POOL_ID": "us-east-2_realpool",
    "COGNITO_APP_CLIENT_ID": "realclient",
    "TURNSTILE_SECRET_KEY": "0x-fictional",
    "TURNSTILE_SITE_KEY": "0x-fictional-site",
    "AWS_ACCESS_KEY_ID": "AKIAFICTIONAL",
    "RENDER_EXTERNAL_URL": "https://creating-tomorrow.onrender.com",
    "CT_MODEL": "claude-sonnet-5",
    "PGHOST": "dpg-xyz.render.com",
}


class A_TheLauncherCanOnlyPointAtLocalFakes(unittest.TestCase):
    def setUp(self):
        self.mod = load_launcher()
        self.workdir = tempfile.mkdtemp(prefix="ct-e2e-test-")

    def test_every_real_setting_is_removed_and_replaced_by_a_local_fake(self):
        safe = self.mod.build_safe_env(REAL_ENV, self.workdir)
        self.mod.assert_safe_env(safe)  # does not raise
        self.assertTrue(safe["DATABASE_URL"].startswith("sqlite:///"))
        self.assertNotIn("render.com", " ".join(str(v) for v in safe.values()))
        self.assertEqual(safe["ANTHROPIC_API_KEY"], self.mod.FAKE_KEY)
        self.assertTrue(safe["ANTHROPIC_BASE_URL"].startswith("http://127.0.0.1:"))
        self.assertEqual((safe["COGNITO_REGION"], safe["COGNITO_USER_POOL_ID"]), (self.mod.FAKE_REGION, self.mod.FAKE_POOL))
        for gone in ("TURNSTILE_SECRET_KEY", "TURNSTILE_SITE_KEY", "AWS_ACCESS_KEY_ID", "RENDER_EXTERNAL_URL", "PGHOST", "CT_MODEL"):
            self.assertNotIn(gone, safe)
        self.assertEqual(safe["PATH"], "/usr/bin")  # harmless variables pass through

    def test_the_safety_check_refuses_each_unsafe_value_on_its_own(self):
        good = self.mod.build_safe_env({}, self.workdir)
        for key, bad in (("DATABASE_URL", "postgresql://user:pw@dpg.render.com/db"), ("ANTHROPIC_API_KEY", "sk-ant-fictional"),
                         ("ANTHROPIC_BASE_URL", "https://api.anthropic.com"), ("COGNITO_REGION", "us-east-2"),
                         ("COGNITO_USER_POOL_ID", "us-east-2_realpool"), ("TURNSTILE_SECRET_KEY", "0x-fictional"), ("CT_E2E", "0"),
                         ("SOME_URL", "https://creatingtomorrow.net/api")):
            with self.assertRaises(SystemExit, msg=key):
                self.mod.assert_safe_env({**good, key: bad})

    def test_the_server_will_not_start_without_the_explicit_switch(self):
        with mock.patch.dict(os.environ, {k: v for k, v in os.environ.items() if k != "CT_E2E"}, clear=True):
            with self.assertRaises(SystemExit):
                self.mod.main()

    def test_the_sign_in_client_id_comes_from_the_page_and_is_public(self):
        self.assertEqual(self.mod.frontend_client_id(), "5rfhr0o7799aa41a5odrt9i9hd")  # the value already in render.yaml and auth.js


class B_MintedTokensWorkThroughTheRealCheckAndOnlyThatKey(unittest.TestCase):
    def setUp(self):
        self.mod = load_launcher()
        self.pem, self.jwk = self.mod.make_keys()
        self.other_pem, _ = self.mod.make_keys()
        engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        Base.metadata.create_all(engine)
        self.Session = sessionmaker(bind=engine)
        app = FastAPI()
        app.include_router(router, prefix="/api/career")

        def session():
            s = self.Session()
            try:
                yield s
            finally:
                s.close()

        app.dependency_overrides[get_db_session] = session
        self.client = TestClient(app)
        self.patches = [mock.patch.object(deps, "COGNITO_REGION", self.mod.FAKE_REGION), mock.patch.object(deps, "COGNITO_USER_POOL_ID", self.mod.FAKE_POOL),
                        mock.patch.object(deps, "COGNITO_APP_CLIENT_ID", "client-x"),
                        mock.patch.object(deps, "_jwks_cache", None), mock.patch.object(deps, "_jwks_fetched_at", None)]
        for p in self.patches:
            p.start()
        # no request may leave the machine while these tests run: any attempt to fetch the sign-in key list fails the test
        self.fetch = mock.patch.object(deps, "_fetch_jwks", side_effect=AssertionError("a request to Cognito was attempted"))
        self.fetch.start()
        self.mod.plant_keys(self.jwk)

    def tearDown(self):
        self.fetch.stop()
        for p in self.patches:
            p.stop()

    def headers(self, token):
        return {"Authorization": f"Bearer {token}"}

    def test_a_minted_token_is_accepted_for_the_planted_key(self):
        token = self.mod.mint_token(self.pem, self.mod.SUB_A, "client-x")
        res = self.client.get("/api/career/me", headers=self.headers(token))
        self.assertEqual(res.status_code, 200, res.text)

    def test_a_token_from_any_other_key_is_refused_and_cognito_is_never_asked(self):
        token = self.mod.mint_token(self.other_pem, self.mod.SUB_A, "client-x")
        res = self.client.get("/api/career/me", headers=self.headers(token))
        self.assertEqual(res.status_code, 401)

    def test_an_id_token_a_wrong_client_and_an_expired_token_are_refused(self):
        for token in (self.mod.mint_token(self.pem, self.mod.SUB_A, "client-x", token_use="id"),
                      self.mod.mint_token(self.pem, self.mod.SUB_A, "someone-elses-client"),
                      self.mod.mint_token(self.pem, self.mod.SUB_A, "client-x", lifetime=-60)):
            self.assertEqual(self.client.get("/api/career/me", headers=self.headers(token)).status_code, 401)

    def test_the_two_fictional_people_are_different_accounts(self):
        a = self.client.get("/api/career/me", headers=self.headers(self.mod.mint_token(self.pem, self.mod.SUB_A, "client-x"))).json()
        b = self.client.get("/api/career/me", headers=self.headers(self.mod.mint_token(self.pem, self.mod.SUB_B, "client-x"))).json()
        self.assertNotEqual(a, b)


if __name__ == "__main__":
    unittest.main()
