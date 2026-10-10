"""The invisible bot check (Cloudflare Turnstile) in front of the nine public AI tools (risk-audit finding F-01)."""
import contextlib
import io
import json
import os
import re
import unittest
from unittest import mock

from fastapi.testclient import TestClient

import abuse_guard
import main
import turnstile

CF = {"CF-Ray": "abc123-ORD", "CF-Connecting-IP": "203.0.113.7"}
KEYS = {"TURNSTILE_SITE_KEY": "0x4AAAAAAAsitekeyPUBLIC", "TURNSTILE_SECRET_KEY": "0x4AAAAAAAsecretkeyPRIVATE"}
SECRET = KEYS["TURNSTILE_SECRET_KEY"]
PUBLIC_AI = sorted(abuse_guard.PUBLIC_AI_PATHS)
FRONTEND = os.path.join(os.path.dirname(__file__), "..", "..", "frontend")


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def read(self):
        return json.dumps(self.payload).encode()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class VerifyTests(unittest.TestCase):
    def setUp(self):
        env = mock.patch.dict(os.environ, KEYS)
        env.start()
        self.addCleanup(env.stop)

    def verify_with(self, payload=None, error=None):
        def fake_urlopen(request, timeout=None):
            self.sent = request
            if error:
                raise error
            return FakeResponse(payload)
        with mock.patch.object(turnstile.urllib.request, "urlopen", fake_urlopen):
            return turnstile.verify("a-token")

    def test_a_genuine_token_from_our_own_site_passes(self):
        self.assertEqual(self.verify_with({"success": True, "hostname": "creatingtomorrow.net"}), (True, "ok"))
        self.assertEqual(self.verify_with({"success": True, "hostname": "WWW.creatingtomorrow.net"}), (True, "ok"))

    def test_the_secret_goes_to_cloudflare_only_and_in_the_body(self):
        self.verify_with({"success": True, "hostname": "creatingtomorrow.net"})
        self.assertTrue(self.sent.full_url.startswith("https://challenges.cloudflare.com/"))
        self.assertIn(b"response=a-token", self.sent.data)
        self.assertNotIn(SECRET, self.sent.full_url)

    def test_failed_and_foreign_tokens_are_refused(self):
        self.assertEqual(self.verify_with({"success": False, "error-codes": ["invalid-input-response"]}), (False, "invalid"))
        self.assertEqual(self.verify_with({"success": True, "hostname": "someone-elses-site.example"}), (False, "invalid"))
        self.assertEqual(self.verify_with(["not", "a", "dict"]), (False, "invalid"))

    def test_an_unreachable_cloudflare_never_opens_the_door(self):
        self.assertEqual(self.verify_with(error=OSError("network down")), (False, "unreachable"))

    def test_the_check_needs_both_keys(self):
        for only in ("TURNSTILE_SITE_KEY", "TURNSTILE_SECRET_KEY"):
            with mock.patch.dict(os.environ, {k: v for k, v in KEYS.items() if k == only}, clear=False):
                other = ({"TURNSTILE_SITE_KEY", "TURNSTILE_SECRET_KEY"} - {only}).pop()
                with mock.patch.dict(os.environ, {other: ""}):
                    self.assertFalse(turnstile.enabled(), f"only {only} set")
        self.assertTrue(turnstile.enabled())


class GateTests(unittest.TestCase):
    def setUp(self):
        abuse_guard.reset()
        self.client = TestClient(main.app)
        env = mock.patch.dict(os.environ, {"RATE_LIMIT_PUBLIC_IP": "50/60", "RATE_LIMIT_PUBLIC_GLOBAL": "500/60"})
        env.start()
        self.addCleanup(env.stop)
        self.addCleanup(abuse_guard.reset)

    def post(self, path="/api/analyze", token=None):
        headers = dict(CF)
        if token:
            headers["X-Turnstile-Token"] = token
        return self.client.post(path, headers=headers)

    def test_off_by_default_so_deploying_the_code_changes_nothing(self):
        with mock.patch.dict(os.environ, {"TURNSTILE_SITE_KEY": "", "TURNSTILE_SECRET_KEY": ""}):
            for path in PUBLIC_AI:
                self.assertNotIn(self.post(path).status_code, (403, 503), path)

    def test_on_a_request_with_no_token_is_refused_for_every_tool(self):
        with mock.patch.dict(os.environ, KEYS), mock.patch.object(turnstile, "verify", side_effect=AssertionError("must not be asked")):
            for path in PUBLIC_AI:
                res = self.post(path)
                self.assertEqual(res.status_code, 403, path)
                self.assertIn("confirm that you're a person", res.json()["detail"])

    def test_a_bad_token_is_refused_and_a_good_one_goes_through_to_the_tool(self):
        with mock.patch.dict(os.environ, KEYS):
            with mock.patch.object(turnstile, "verify", return_value=(False, "invalid")):
                self.assertEqual(self.post(token="forged").status_code, 403)
            with mock.patch.object(turnstile, "verify", return_value=(True, "ok")):
                res = self.post(token="genuine")
                self.assertNotIn(res.status_code, (403, 503), "a genuine token reaches the tool (which then asks for its form fields)")

    def test_an_unreachable_cloudflare_gives_a_try_again_answer_with_retry_after(self):
        with mock.patch.dict(os.environ, KEYS), mock.patch.object(turnstile, "verify", return_value=(False, "unreachable")):
            res = self.post(token="anything")
        self.assertEqual(res.status_code, 503)
        self.assertEqual(res.headers.get("Retry-After"), "30")

    def test_an_oversized_token_is_refused_without_asking_cloudflare(self):
        with mock.patch.dict(os.environ, KEYS), mock.patch.object(turnstile, "verify", side_effect=AssertionError("must not be asked")):
            self.assertEqual(self.post(token="x" * 5000).status_code, 403)

    def test_only_the_nine_ai_tools_need_a_token(self):
        with mock.patch.dict(os.environ, KEYS):
            self.assertEqual(self.client.get("/api/health", headers=CF).status_code, 200)
            self.assertEqual(self.client.get("/index.html", headers=CF).status_code, 200)
            self.assertEqual(self.client.get("/api/turnstile-config", headers=CF).status_code, 200)

    def test_bad_attempts_still_count_against_the_visitor_rate_limit(self):
        with mock.patch.dict(os.environ, {**KEYS, "RATE_LIMIT_PUBLIC_IP": "3/60"}):
            codes = [self.post().status_code for _ in range(5)]
        self.assertEqual(codes[:3], [403, 403, 403])
        self.assertEqual(codes[3:], [429, 429])

    def test_neither_the_token_nor_the_secret_is_ever_printed(self):
        out = io.StringIO()
        with mock.patch.dict(os.environ, KEYS), mock.patch.object(turnstile, "verify", return_value=(False, "invalid")), contextlib.redirect_stdout(out):
            self.post(token="SUPER-SECRET-LOOKING-TOKEN-123")
        self.assertIn("bot check", out.getvalue())
        self.assertNotIn("SUPER-SECRET-LOOKING-TOKEN-123", out.getvalue())
        self.assertNotIn(SECRET, out.getvalue())


class ConfigAndHealthTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(main.app)

    def test_the_page_config_has_the_public_key_and_never_the_secret(self):
        with mock.patch.dict(os.environ, KEYS):
            res = self.client.get("/api/turnstile-config")
        self.assertEqual(res.json(), {"enabled": True, "site_key": KEYS["TURNSTILE_SITE_KEY"]})
        self.assertNotIn(SECRET, res.text)
        self.assertEqual(res.headers.get("Cache-Control"), "no-store")

    def test_the_page_config_is_off_without_both_keys(self):
        with mock.patch.dict(os.environ, {"TURNSTILE_SITE_KEY": "", "TURNSTILE_SECRET_KEY": ""}):
            self.assertEqual(self.client.get("/api/turnstile-config").json(), {"enabled": False, "site_key": None})

    def test_the_health_page_says_on_or_off_and_shows_no_key(self):
        with mock.patch.object(main, "check_ai_key", lambda: "ok"):
            with mock.patch.dict(os.environ, KEYS):
                on = self.client.get("/api/health")
            with mock.patch.dict(os.environ, {"TURNSTILE_SITE_KEY": "", "TURNSTILE_SECRET_KEY": ""}):
                off = self.client.get("/api/health")
        self.assertEqual(on.json()["bot_check"], "on")
        self.assertEqual(off.json()["bot_check"], "off")
        for text in (on.text, off.text):
            self.assertNotIn(SECRET, text)
            self.assertNotIn(KEYS["TURNSTILE_SITE_KEY"], text)


class PagesAndPolicyTests(unittest.TestCase):
    def read(self, name):
        with open(os.path.join(FRONTEND, name), encoding="utf-8") as handle:
            return handle.read()

    def test_the_browser_script_lists_exactly_the_guarded_tools(self):
        js = self.read("turnstile-gate.js")
        listed = set(re.findall(r'"(/api/[a-z-]+)"', js.split("var AI_PATHS = [")[1].split("];")[0]))
        self.assertEqual(listed, set(abuse_guard.PUBLIC_AI_PATHS))

    def test_the_browser_script_holds_no_secret(self):
        js = self.read("turnstile-gate.js")
        self.assertNotRegex(js, r"0x4[A-Za-z0-9_-]{15,}")
        self.assertNotIn("TURNSTILE_SECRET", js)

    def test_every_tool_page_loads_the_script_before_its_own_script(self):
        for page, own in (("scratch.html", "scratch.js"), ("tool.html", "app.js"), ("elevate.html", "elevate.js"),
                          ("spotlight.html", "spotlight.js"), ("prepare.html", "prepare.js")):
            html = self.read(page)
            self.assertIn('<script src="turnstile-gate.js"></script>', html, page)
            self.assertLess(html.index("turnstile-gate.js"), html.index(own), page)

    def test_the_security_policy_allows_cloudflare_for_scripts_frames_and_connections_only(self):
        csp = main.CONTENT_SECURITY_POLICY
        for directive in ("script-src", "connect-src", "frame-src"):
            part = [p for p in csp.split("; ") if p.startswith(directive)][0]
            self.assertIn("https://challenges.cloudflare.com", part, directive)
        for directive in ("img-src", "default-src", "form-action"):
            part = [p for p in csp.split("; ") if p.startswith(directive)][0]
            self.assertNotIn("cloudflare", part, directive)


if __name__ == "__main__":
    unittest.main()
