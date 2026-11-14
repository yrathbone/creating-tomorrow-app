"""GET /api/career/auth-config: the public, read-only sign-in configuration. Offline; no Cognito call."""
import unittest
from unittest import mock

from fastapi import FastAPI
from fastapi.testclient import TestClient

import auth.dependencies as deps
from career.routes import router as career_router

GOOD = {"COGNITO_REGION": "us-east-2", "COGNITO_USER_POOL_ID": "us-east-2_TESTPOOL1", "COGNITO_APP_CLIENT_ID": "testclient123456"}


def _client():
    app = FastAPI()
    app.include_router(career_router, prefix="/api/career")
    return TestClient(app, raise_server_exceptions=False)


class AuthConfigEndpoint(unittest.TestCase):
    def setUp(self):
        self.client = _client()

    def _with(self, **values):
        settings = dict(GOOD, **values)
        return mock.patch.multiple(deps, COGNITO_REGION=settings["COGNITO_REGION"],
                                   COGNITO_USER_POOL_ID=settings["COGNITO_USER_POOL_ID"],
                                   COGNITO_APP_CLIENT_ID=settings["COGNITO_APP_CLIENT_ID"])

    def test_returns_only_the_three_public_values_and_needs_no_token(self):
        with self._with():
            r = self.client.get("/api/career/auth-config")  # no Authorization header
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json(), {"region": "us-east-2", "user_pool_id": "us-east-2_TESTPOOL1", "app_client_id": "testclient123456"})
        self.assertEqual(r.headers.get("cache-control"), "no-store")

    def test_production_format_values_are_accepted(self):
        # The shape of the values the production service already uses (render.yaml). The pool and client are not secrets.
        with self._with(COGNITO_USER_POOL_ID="us-east-2_uLhNvjpep", COGNITO_APP_CLIENT_ID="5rfhr0o7799aa41a5odrt9i9hd"):
            r = self.client.get("/api/career/auth-config")
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["user_pool_id"], "us-east-2_uLhNvjpep")

    def test_missing_values_answer_503_with_no_guess(self):
        for name in ("COGNITO_REGION", "COGNITO_USER_POOL_ID", "COGNITO_APP_CLIENT_ID"):
            with self.subTest(missing=name):
                values = dict(GOOD, **{name: None})
                with mock.patch.multiple(deps, COGNITO_REGION=values["COGNITO_REGION"], COGNITO_USER_POOL_ID=values["COGNITO_USER_POOL_ID"],
                                         COGNITO_APP_CLIENT_ID=values["COGNITO_APP_CLIENT_ID"]):
                    r = self.client.get("/api/career/auth-config")
                self.assertEqual(r.status_code, 503)
                self.assertNotIn("user_pool_id", r.text)

    def test_pool_region_mismatch_answers_503(self):
        with self._with(COGNITO_USER_POOL_ID="eu-west-1_TESTPOOL1"):
            self.assertEqual(self.client.get("/api/career/auth-config").status_code, 503)

    def test_malformed_pool_or_region_answers_503(self):
        for bad in ("us-east-2", "us-east-2_", "us-east-2_bad pool", "US-EAST-2_TESTPOOL1", "us-east-2_TEST;POOL"):
            with self.subTest(pool=bad):
                with self._with(COGNITO_USER_POOL_ID=bad):
                    self.assertEqual(self.client.get("/api/career/auth-config").status_code, 503)
        for bad_region in ("useast2", "us-east", "us_east-2"):
            with self.subTest(region=bad_region):
                with self._with(COGNITO_REGION=bad_region):
                    self.assertEqual(self.client.get("/api/career/auth-config").status_code, 503)

    def test_malformed_client_id_answers_503(self):
        for bad in ("short", "has space in it", "client-with-dash!", "x" * 65):
            with self.subTest(client=bad):
                with self._with(COGNITO_APP_CLIENT_ID=bad):
                    self.assertEqual(self.client.get("/api/career/auth-config").status_code, 503)


if __name__ == "__main__":
    unittest.main()
