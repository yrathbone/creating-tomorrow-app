"""Forged tokens must not make the server hammer Cognito for its keys (risk-audit finding F-06)."""
import unittest
from unittest import mock

from fastapi import HTTPException
from jose import JWTError

import auth.dependencies as deps

KEY_A = {"kid": "key-a", "kty": "RSA"}
KEY_B = {"kid": "key-b", "kty": "RSA"}


class Clock:
    def __init__(self):
        self.now = 10_000.0

    def __call__(self):
        return self.now


class JwksThrottleTests(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.fetches = 0
        self.published = {"keys": [KEY_A]}
        self.fail = False

        def fetch():
            self.fetches += 1
            if self.fail:
                raise OSError("network down")
            return {"keys": list(self.published["keys"])}

        for p in (
            mock.patch.object(deps, "_jwks_cache", None),
            mock.patch.object(deps, "_jwks_fetched_at", None),
            mock.patch.object(deps, "_jwks_last_attempt", None),
            mock.patch.object(deps, "_unknown_kids", {}),
            mock.patch.object(deps, "_fetch_jwks", fetch),
            mock.patch.object(deps.time, "monotonic", self.clock),
        ):
            p.start()
            self.addCleanup(p.stop)

    def test_the_keys_are_fetched_once_and_then_reused(self):
        for _ in range(20):
            self.assertEqual(deps._get_signing_key("key-a"), KEY_A)
        self.assertEqual(self.fetches, 1)

    def test_a_flood_of_forged_key_ids_causes_one_extra_fetch_at_most_per_minute(self):
        deps._get_signing_key("key-a")
        for i in range(200):
            with self.assertRaises(JWTError):
                deps._get_signing_key(f"forged-{i}")
        self.assertEqual(self.fetches, 1, "inside the first minute the unknown ids cause no new fetch")
        self.clock.now += 61
        for i in range(200):                           # the same forged ids are remembered for 5 minutes: still no fetch
            with self.assertRaises(JWTError):
                deps._get_signing_key(f"forged-{i}")
        self.assertEqual(self.fetches, 1)
        for i in range(200):                           # brand-new forged ids: ONE refetch covers the whole flood
            with self.assertRaises(JWTError):
                deps._get_signing_key(f"fresh-{i}")
        self.assertEqual(self.fetches, 2)

    def test_the_same_unknown_id_is_remembered(self):
        deps._get_signing_key("key-a")
        self.clock.now += 120
        with self.assertRaises(JWTError):
            deps._get_signing_key("ghost")
        fetches = self.fetches
        self.clock.now += 100                          # still inside the 5 minutes
        for _ in range(10):
            with self.assertRaises(JWTError):
                deps._get_signing_key("ghost")
        self.assertEqual(self.fetches, fetches)

    def test_a_genuine_key_rotation_is_picked_up_after_the_minimum_wait(self):
        deps._get_signing_key("key-a")
        self.published["keys"].append(KEY_B)           # Cognito rotates in a new key
        self.clock.now += 61
        self.assertEqual(deps._get_signing_key("key-b"), KEY_B)
        self.assertEqual(self.fetches, 2)

    def test_the_key_list_is_refreshed_after_it_gets_old(self):
        deps._get_signing_key("key-a")
        self.clock.now += deps.JWKS_MAX_AGE_SECONDS + 1
        deps._get_signing_key("key-a")
        self.assertEqual(self.fetches, 2)

    def test_a_cognito_outage_does_not_sign_out_people_who_already_have_keys(self):
        deps._get_signing_key("key-a")
        self.fail = True
        self.clock.now += deps.JWKS_MAX_AGE_SECONDS + 1
        self.assertEqual(deps._get_signing_key("key-a"), KEY_A, "stale keys keep working")
        with self.assertRaises(JWTError):
            deps._get_signing_key("unknown")           # and it does not crash

    def test_no_keys_and_no_connection_is_a_clear_503_not_a_crash(self):
        self.fail = True
        with self.assertRaises(HTTPException) as caught:
            deps._get_signing_key("key-a")
        self.assertEqual(caught.exception.status_code, 503)

    def test_keys_planted_by_hand_never_expire(self):
        with mock.patch.object(deps, "_jwks_cache", {"keys": [KEY_A]}):
            self.clock.now += 10 * deps.JWKS_MAX_AGE_SECONDS
            self.assertEqual(deps._get_signing_key("key-a"), KEY_A)
            self.assertEqual(self.fetches, 0)

    def test_the_memory_of_unknown_ids_is_bounded(self):
        deps._get_signing_key("key-a")
        for i in range(deps.MAX_REMEMBERED_UNKNOWN_KIDS + 50):
            with self.assertRaises(JWTError):
                deps._get_signing_key(f"x{i}")
        self.assertLessEqual(len(deps._unknown_kids), deps.MAX_REMEMBERED_UNKNOWN_KIDS)


if __name__ == "__main__":
    unittest.main()
