"""Limits on the paid AI tools and on request size (risk-audit findings F-01, F-03, F-04)."""
import os
import unittest
from types import SimpleNamespace
from unittest import mock

from fastapi import HTTPException
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

import abuse_guard
import main
from abuse_guard import InFlight, SlidingWindowLimiter, client_key, rules_from_env, user_ai_guard
from career.routes import router as career_router

PUBLIC_AI = ["/api/analyze", "/api/refine", "/api/elevate-start", "/api/elevate-discover", "/api/elevate-finalize",
             "/api/profile-review", "/api/prepare", "/api/scratch-entry", "/api/scratch-finalize"]
SIGNED_IN_AI = ["/skills-tidy-suggest", "/resume-start", "/resume-discover", "/job-compare", "/job-keyword-check",
                "/job-discover", "/job-build-resume", "/build-general-resume", "/skill-scan"]
CF = {"CF-Ray": "abc123-ORD", "CF-Connecting-IP": "203.0.113.7"}


class LimiterTests(unittest.TestCase):
    def test_allows_up_to_the_limit_then_refuses_with_a_wait_time(self):
        lim = SlidingWindowLimiter()
        rules = [(3, 60)]
        for i in range(3):
            self.assertEqual(lim.check("a", rules, now=100 + i), (True, 0))
        allowed, wait = lim.check("a", rules, now=103)
        self.assertFalse(allowed)
        self.assertTrue(1 <= wait <= 60)

    def test_the_window_rolls_and_a_refused_hit_is_not_counted(self):
        lim = SlidingWindowLimiter()
        rules = [(2, 60)]
        lim.check("a", rules, now=0)
        lim.check("a", rules, now=10)
        for t in (20, 30, 40, 50):          # hammering while blocked must not extend the block
            self.assertFalse(lim.check("a", rules, now=t)[0])
        self.assertTrue(lim.check("a", rules, now=61)[0], "the first hit has aged out")
        self.assertFalse(lim.check("a", rules, now=62)[0], "the second is still inside the window")
        self.assertTrue(lim.check("a", rules, now=71)[0])

    def test_keys_are_independent(self):
        lim = SlidingWindowLimiter()
        self.assertTrue(lim.check("a", [(1, 60)], now=0)[0])
        self.assertFalse(lim.check("a", [(1, 60)], now=1)[0])
        self.assertTrue(lim.check("b", [(1, 60)], now=1)[0])

    def test_every_rule_applies(self):
        lim = SlidingWindowLimiter()
        rules = [(5, 10), (6, 3600)]          # fast burst limit and an hourly limit
        t = 0
        for _ in range(6):
            t += 11                             # slow enough to pass the burst rule
            self.assertTrue(lim.check("a", rules, now=t)[0])
        self.assertFalse(lim.check("a", rules, now=t + 11)[0], "the hourly rule refuses the 7th")

    def test_memory_is_bounded(self):
        lim = SlidingWindowLimiter()
        lim.MAX_KEYS = 50
        for i in range(500):
            lim.check(f"k{i}", [(1, 1000)], now=float(i))
        self.assertLessEqual(len(lim._hits), 50 + 1)


class RulesAndKeysTests(unittest.TestCase):
    def test_rules_are_read_from_the_environment_with_a_safe_fallback(self):
        with mock.patch.dict(os.environ, {"RATE_LIMIT_USER": "2/30,9/60"}):
            self.assertEqual(rules_from_env("RATE_LIMIT_USER"), [(2, 30), (9, 60)])
        for bad in ("nonsense", "0/60", "5/0", "5/x", ""):
            with mock.patch.dict(os.environ, {"RATE_LIMIT_USER": bad}):
                self.assertEqual(rules_from_env("RATE_LIMIT_USER"), [(10, 60), (60, 3600), (300, 86400)], bad)

    def test_the_visitor_address_comes_from_cloudflare_and_only_when_cloudflare_vouches_for_it(self):
        self.assertEqual(client_key({"cf-ray": "x", "cf-connecting-ip": "203.0.113.7"}, ("10.0.0.1", 1)), "203.0.113.7")
        # a visitor-supplied header with no Cloudflare ray is ignored
        self.assertEqual(client_key({"cf-connecting-ip": "203.0.113.7"}, ("198.51.100.4", 1)), "198.51.100.4")

    def test_x_forwarded_for_is_never_trusted(self):
        self.assertEqual(client_key({"x-forwarded-for": "1.2.3.4, 5.6.7.8"}, ("198.51.100.4", 1)), "198.51.100.4")
        self.assertEqual(client_key({"cf-ray": "x", "cf-connecting-ip": "203.0.113.7", "x-forwarded-for": "1.1.1.1"}, None), "203.0.113.7")

    def test_bad_or_missing_addresses_share_one_bucket_and_ipv6_is_grouped_by_64(self):
        self.assertEqual(client_key({"cf-ray": "x", "cf-connecting-ip": "not-an-ip"}, None), "unknown")
        self.assertEqual(client_key({}, None), "unknown")
        a = client_key({"cf-ray": "x", "cf-connecting-ip": "2001:db8:1:2:aaaa::1"}, None)
        b = client_key({"cf-ray": "x", "cf-connecting-ip": "2001:db8:1:2:bbbb::9"}, None)
        c = client_key({"cf-ray": "x", "cf-connecting-ip": "2001:db8:1:3::1"}, None)
        self.assertEqual(a, b)
        self.assertNotEqual(a, c)


class MiddlewareTests(unittest.TestCase):
    def setUp(self):
        abuse_guard.reset()
        self.client = TestClient(main.app)
        self.env = mock.patch.dict(os.environ, {"RATE_LIMIT_PUBLIC_IP": "3/60", "RATE_LIMIT_PUBLIC_GLOBAL": "100/60", "MAX_CONCURRENT_AI": "2"})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        abuse_guard.reset()

    def post(self, path="/api/analyze", headers=None, **kw):
        return self.client.post(path, headers=headers or CF, **kw)

    def test_a_visitor_is_refused_after_their_limit_with_a_friendly_message_and_retry_after(self):
        for _ in range(3):
            self.assertEqual(self.post().status_code, 422)         # reaches the route (no file sent), costs nothing
        res = self.post()
        self.assertEqual(res.status_code, 429)
        self.assertIn("Please wait a few minutes", res.json()["detail"])
        self.assertTrue(int(res.headers["retry-after"]) >= 1)
        self.assertIn("x-content-type-options", res.headers, "refusals still carry the security headers")

    def test_another_visitor_is_not_affected(self):
        for _ in range(4):
            self.post()
        other = self.post(headers={"CF-Ray": "zzz", "CF-Connecting-IP": "198.51.100.99"})
        self.assertEqual(other.status_code, 422)

    def test_a_forged_address_header_without_a_cloudflare_ray_does_not_buy_a_fresh_allowance(self):
        for i in range(4):
            res = self.post(headers={"CF-Connecting-IP": f"198.51.100.{i}"})   # no CF-Ray: all count against the real connection
        self.assertEqual(res.status_code, 429)

    def test_every_public_ai_tool_is_limited(self):
        for path in PUBLIC_AI:
            abuse_guard.reset()
            codes = [self.post(path).status_code for _ in range(4)]
            self.assertEqual(codes[-1], 429, path)
            self.assertNotIn(429, codes[:3], path)

    def test_the_global_ceiling_holds_even_across_many_visitors(self):
        with mock.patch.dict(os.environ, {"RATE_LIMIT_PUBLIC_IP": "100/60", "RATE_LIMIT_PUBLIC_GLOBAL": "5/60"}):
            codes = [self.post(headers={"CF-Ray": "r", "CF-Connecting-IP": f"198.51.100.{i}"}).status_code for i in range(7)]
        self.assertEqual(codes[:5], [422] * 5)
        self.assertEqual(codes[5:], [429, 429])

    def test_other_routes_and_methods_are_not_limited(self):
        for _ in range(10):
            self.assertEqual(self.client.get("/api/health", headers=CF).status_code, 200)
        for _ in range(5):
            self.assertNotEqual(self.client.get("/api/analyze", headers=CF).status_code, 429)   # GET is not a tool call
        for _ in range(5):
            self.assertEqual(self.client.post("/api/generate", headers=CF, json={"resume_data": {}}).status_code, 400)   # no AI, not limited

    def test_too_many_at_once_gets_a_busy_answer_and_the_slot_is_released_afterwards(self):
        self.assertTrue(abuse_guard.IN_FLIGHT.acquire())
        self.assertTrue(abuse_guard.IN_FLIGHT.acquire())
        busy = self.post()
        self.assertEqual(busy.status_code, 503)
        self.assertIn("busy", busy.json()["detail"])
        abuse_guard.IN_FLIGHT.release()
        self.assertEqual(self.post(headers={"CF-Ray": "q", "CF-Connecting-IP": "198.51.100.50"}).status_code, 422)
        abuse_guard.IN_FLIGHT.release()
        self.assertEqual(abuse_guard.IN_FLIGHT.count, 0, "a finished request gives its slot back")

    def test_a_json_body_over_the_limit_is_refused_before_it_is_read(self):
        with mock.patch.dict(os.environ, {"MAX_JSON_REQUEST_BYTES": "1000"}):
            res = self.client.post("/api/generate", json={"resume_data": {"name": "x" * 5000}})
            self.assertEqual(res.status_code, 413)
            self.assertIn("too large", res.json()["detail"])
            ok = self.client.post("/api/generate", json={"resume_data": {}})
            self.assertEqual(ok.status_code, 400, "a small body still reaches the route")

    def test_a_form_upload_over_the_limit_is_refused(self):
        with mock.patch.dict(os.environ, {"MAX_UPLOAD_REQUEST_BYTES": "2000"}):
            res = self.client.post("/api/refine", headers=CF, files={"resume_file": ("a.txt", b"x" * 5000)})
            self.assertEqual(res.status_code, 413)

    def test_a_streamed_body_with_no_declared_length_is_cut_off_too(self):
        def chunks():
            for _ in range(10):
                yield b"x" * 500
        with mock.patch.dict(os.environ, {"MAX_JSON_REQUEST_BYTES": "1000"}):
            res = self.client.post("/api/generate", content=chunks(), headers={"Content-Type": "application/json"})
        self.assertEqual(res.status_code, 413)

    def test_a_normal_sized_upload_still_gets_through_to_the_route(self):
        res = self.client.post("/api/refine", headers=CF, files={"resume_file": ("a.txt", b"")})
        self.assertEqual(res.status_code, 400, "an empty file is the route's own friendly 400, not a limit")


class SignedInGuardTests(unittest.TestCase):
    def setUp(self):
        abuse_guard.reset()

    def tearDown(self):
        abuse_guard.reset()

    def test_each_account_has_its_own_limit(self):
        with mock.patch.dict(os.environ, {"RATE_LIMIT_USER": "2/60"}):
            for _ in range(2):
                g = user_ai_guard(SimpleNamespace(id=1))
                next(g)
                g.close()
            g = user_ai_guard(SimpleNamespace(id=1))
            with self.assertRaises(HTTPException) as caught:
                next(g)
            self.assertEqual(caught.exception.status_code, 429)
            self.assertIn("Retry-After", caught.exception.headers)
            other = user_ai_guard(SimpleNamespace(id=2))
            next(other)
            other.close()

    def test_a_slot_is_held_while_the_route_runs_and_released_after_even_on_an_error(self):
        g = user_ai_guard(SimpleNamespace(id=3))
        next(g)
        self.assertEqual(abuse_guard.IN_FLIGHT.count, 1)
        with self.assertRaises(RuntimeError):
            g.throw(RuntimeError("route failed"))
        self.assertEqual(abuse_guard.IN_FLIGHT.count, 0)

    def test_a_full_house_gets_a_busy_answer(self):
        with mock.patch.dict(os.environ, {"MAX_CONCURRENT_AI": "1"}):
            self.assertTrue(abuse_guard.IN_FLIGHT.acquire())
            with self.assertRaises(HTTPException) as caught:
                next(user_ai_guard(SimpleNamespace(id=4)))
            self.assertEqual(caught.exception.status_code, 503)

    def test_every_signed_in_ai_route_has_the_guard_and_no_other_route_does(self):
        guarded, other = set(), set()
        for r in career_router.routes:
            if not isinstance(r, APIRoute):
                continue
            has = any(d.dependency is user_ai_guard for d in r.dependencies)
            (guarded if has else other).add(r.path)
        self.assertEqual(guarded, set(SIGNED_IN_AI))
        self.assertFalse(guarded & other)

    def test_every_public_ai_path_is_in_the_guarded_list(self):
        self.assertEqual(set(PUBLIC_AI), set(abuse_guard.PUBLIC_AI_PATHS))
        main_ai = {r.path for r in main.app.routes if isinstance(r, APIRoute) and r.path.startswith("/api/") and "POST" in r.methods}
        self.assertTrue(set(PUBLIC_AI) <= main_ai, "every guarded path is a real route")


if __name__ == "__main__":
    unittest.main()
