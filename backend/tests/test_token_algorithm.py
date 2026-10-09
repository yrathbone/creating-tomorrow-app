"""python-jose (the sign-in library until 2026-10-09, replaced by PyJWT) had an algorithm-confusion bug (CVE-2024-33663 / CVE-2026-85394): a token signed with HS256, using the
public key as the secret, can pass when the caller does not restrict the algorithm. Our sign-in check accepts RS256 only, so it
must refuse these forged tokens. This test makes the attempt for real, so the protection is proven and stays proven."""
import base64
import hashlib
import hmac
import json
import time
import unittest
from unittest import mock

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials
import jwt
from jwt.algorithms import RSAAlgorithm

import auth.dependencies as deps

REGION, POOL, CLIENT = "us-east-2", "us-east-2_testpool", "testclient123"
ISSUER = f"https://cognito-idp.{REGION}.amazonaws.com/{POOL}"


def b64(raw):
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def forge(claims, secret, alg="HS256", digest=hashlib.sha256):
    """Builds the token by hand, the way an attacker would (the library itself refuses to sign with a public key)."""
    head = b64(json.dumps({"alg": alg, "typ": "JWT", "kid": "key-1"}).encode())
    body = b64(json.dumps(claims).encode())
    signature = hmac.new(secret, f"{head}.{body}".encode(), digest).digest()
    return f"{head}.{body}.{b64(signature)}"


class FakeDb:
    """Stands in for the database session; a forged token must never get this far."""
    def __init__(self):
        self.touched = False

    def query(self, *a, **k):
        self.touched = True
        raise AssertionError("a forged token reached the database")


class AlgorithmConfusionTests(unittest.TestCase):
    def setUp(self):
        self.private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        public = self.private.public_key()
        self.public_pem = public.public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
        self.public_der = public.public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
        self.public_jwk = RSAAlgorithm.to_jwk(public, as_dict=True)
        self.public_jwk["kid"] = "key-1"
        self.claims = {"sub": "attacker", "iss": ISSUER, "token_use": "access", "client_id": CLIENT, "exp": int(time.time()) + 600}
        for p in (
            mock.patch.object(deps, "COGNITO_REGION", REGION),
            mock.patch.object(deps, "COGNITO_USER_POOL_ID", POOL),
            mock.patch.object(deps, "COGNITO_APP_CLIENT_ID", CLIENT),
            mock.patch.object(deps, "_get_signing_key", lambda kid: self.public_jwk),
        ):
            p.start()
            self.addCleanup(p.stop)

    def attempt(self, token):
        db = FakeDb()
        with self.assertRaises(HTTPException) as caught:
            deps.get_current_user(HTTPAuthorizationCredentials(scheme="Bearer", credentials=token), db)
        self.assertEqual(caught.exception.status_code, 401)
        self.assertFalse(db.touched)

    def test_hs256_tokens_signed_with_the_public_key_are_refused(self):
        for label, secret in (("PEM", self.public_pem), ("DER", self.public_der)):
            with self.subTest(label):
                self.attempt(forge(self.claims, secret))

    def test_unsigned_and_wrong_algorithm_tokens_are_refused(self):
        header = b64(json.dumps({"alg": "none", "typ": "JWT", "kid": "key-1"}).encode())
        self.attempt(f"{header}.{b64(json.dumps(self.claims).encode())}.")
        self.attempt(forge(self.claims, self.public_pem, "HS512", hashlib.sha512))

    def test_a_properly_signed_token_still_gets_past_the_signature_check(self):
        """Positive control: the test setup is real, so a genuine RS256 token is not refused at the signature step."""
        private_pem = self.private.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
        token = jwt.encode(self.claims, private_pem.decode(), algorithm="RS256", headers={"kid": "key-1"})
        db = FakeDb()
        with self.assertRaises(AssertionError):  # it reaches the database lookup, which FakeDb refuses
            deps.get_current_user(HTTPAuthorizationCredentials(scheme="Bearer", credentials=token), db)
        self.assertTrue(db.touched)


if __name__ == "__main__":
    unittest.main()
