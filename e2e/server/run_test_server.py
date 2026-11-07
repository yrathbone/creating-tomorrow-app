"""Safe local server for the browser tests (N-06). It can only ever talk to this machine.

What it does, in order:
  1. refuses to run unless CT_E2E=1 (so it cannot be started by accident);
  2. REMOVES every real setting from the environment (database, AI key, Cognito, Turnstile, AWS, Render) and replaces it with a local fake:
       - DATABASE_URL        a throw-away SQLite file in a temp folder;
       - ANTHROPIC_API_KEY   a fake key, and ANTHROPIC_BASE_URL pointing at a closed local port, so any AI call fails at once, on this machine;
       - COGNITO_*           a made-up region and pool (the sign-in key list is planted in memory, so no request ever leaves for Cognito);
       - no Turnstile keys   (the bot check is off, as in local development);
  3. checks the result (assert_safe_env) and stops if anything still points at a real service;
  4. mints access tokens for two FICTIONAL people (A and B) signed with a throw-away key, and writes them to e2e/.auth/ (ignored by git);
  5. starts the app on 127.0.0.1 only.
Nothing here reads a password, cookie or real token, and nothing is written outside the temp folder and e2e/.auth/.
"""
import json
import os
import re
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]                      # the repository root
BACKEND = ROOT / "backend"
AUTH_DIR = HERE.parent / ".auth"

FAKE_REGION = "us-test-1"
FAKE_POOL = "us-test-1_E2EPOOL"
FAKE_KEY = "e2e-fake-anthropic-key-not-real"
CLOSED_LOCAL_PORT = 9                       # the "discard" port: nothing listens, so a connection is refused immediately
KID = "e2e-key-1"
SUB_A = "e2e00000-0000-4000-8000-00000000000a"
SUB_B = "e2e00000-0000-4000-8000-00000000000b"

# Every variable that could point at a real service. All are removed before the fakes are added.
SCRUB_PREFIXES = ("ANTHROPIC_", "COGNITO_", "TURNSTILE_", "AWS_", "RENDER", "CT_", "DATABASE_", "PGHOST", "PGPASSWORD", "PGUSER", "PGDATABASE", "PGPORT")
REAL_SERVICE_PATTERNS = (r"render\.com", r"onrender", r"creatingtomorrow", r"api\.anthropic\.com", r"cognito-idp\.us-east", r"rds\.amazonaws")


def frontend_client_id() -> str:
    """The app client id the page's sign-in library files its tokens under. It is public (it is in the page source); the backend must accept tokens with it."""
    text = (ROOT / "frontend" / "career" / "js" / "auth.js").read_text(encoding="utf-8")
    m = re.search(r'COGNITO_APP_CLIENT_ID\s*=\s*"([^"]+)"', text)
    if not m:
        raise SystemExit("e2e: could not read the sign-in client id from frontend/career/js/auth.js")
    return m.group(1)


def build_safe_env(env: dict, workdir: str, ai_port: int = CLOSED_LOCAL_PORT) -> dict:
    """A copy of `env` with every real setting removed and the local fakes added. Pure function (no side effects) so it can be unit tested."""
    clean = {k: v for k, v in env.items() if not k.upper().startswith(SCRUB_PREFIXES)}
    clean.update({
        "CT_E2E": "1",
        "DATABASE_URL": "sqlite:///" + str(Path(workdir) / "e2e.db").replace("\\", "/"),
        "ANTHROPIC_API_KEY": FAKE_KEY,
        "ANTHROPIC_BASE_URL": f"http://127.0.0.1:{ai_port}",
        "COGNITO_REGION": FAKE_REGION,
        "COGNITO_USER_POOL_ID": FAKE_POOL,
        "COGNITO_APP_CLIENT_ID": frontend_client_id(),
        "CT_ISOLATE_PARSING": "1",
        # Belt and braces for the server process: any outbound HTTP call (AI, Cognito, anything) is sent to a dead local proxy and fails at once.
        "HTTP_PROXY": f"http://127.0.0.1:{CLOSED_LOCAL_PORT}",
        "HTTPS_PROXY": f"http://127.0.0.1:{CLOSED_LOCAL_PORT}",
        "ALL_PROXY": f"http://127.0.0.1:{CLOSED_LOCAL_PORT}",
        "NO_PROXY": "127.0.0.1,localhost",
    })
    return clean


def assert_safe_env(env: dict) -> None:
    """Raises if anything in the environment could reach a real database, AI provider or sign-in tenant. Called before the app starts."""
    problems = []
    if env.get("CT_E2E") != "1":
        problems.append("CT_E2E is not 1")
    url = env.get("DATABASE_URL", "")
    if not url.startswith("sqlite:///"):
        problems.append("DATABASE_URL is not a local SQLite file")
    if env.get("ANTHROPIC_API_KEY") != FAKE_KEY:
        problems.append("ANTHROPIC_API_KEY is not the fake key")
    if not env.get("ANTHROPIC_BASE_URL", "").startswith("http://127.0.0.1:"):
        problems.append("ANTHROPIC_BASE_URL is not local")
    if env.get("COGNITO_REGION") != FAKE_REGION or env.get("COGNITO_USER_POOL_ID") != FAKE_POOL:
        problems.append("Cognito region/pool are not the fakes")
    for k in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"):
        if env.get(k) != f"http://127.0.0.1:{CLOSED_LOCAL_PORT}":
            problems.append(f"{k} is not the dead local proxy")
    if env.get("NO_PROXY") != "127.0.0.1,localhost":
        problems.append("NO_PROXY is not local only")
    for k in ("TURNSTILE_SECRET_KEY", "TURNSTILE_SITE_KEY"):
        if env.get(k):
            problems.append(f"{k} is set")
    for k, v in env.items():
        if k in ("PATH", "PATHEXT", "COMSPEC", "SYSTEMROOT"):
            continue
        for pat in REAL_SERVICE_PATTERNS:
            if re.search(pat, str(v), re.I):
                problems.append(f"{k} mentions a real service ({pat})")
    if problems:
        raise SystemExit("e2e: refusing to start, unsafe environment: " + "; ".join(problems))


def make_keys():
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from jwt.algorithms import RSAAlgorithm
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = private.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()).decode()
    jwk = RSAAlgorithm.to_jwk(private.public_key(), as_dict=True)
    jwk.update({"kid": KID, "use": "sig", "alg": "RS256"})
    return pem, jwk


def mint_token(private_pem: str, sub: str, client_id: str, *, token_use: str = "access", lifetime: int = 24 * 3600) -> str:
    import jwt
    now = int(time.time())
    claims = {"sub": sub, "iss": f"https://cognito-idp.{FAKE_REGION}.amazonaws.com/{FAKE_POOL}", "token_use": token_use, "client_id": client_id,
              "exp": now + lifetime, "iat": now, "username": sub}
    return jwt.encode(claims, private_pem, algorithm="RS256", headers={"kid": KID})


def plant_keys(jwk: dict) -> None:
    """Point the app's token check at OUR public key, in memory. `_jwks_fetched_at = None` means 'planted by hand, never expires', so Cognito is never asked."""
    import auth.dependencies as deps
    deps._jwks_cache = {"keys": [jwk]}
    deps._jwks_fetched_at = None


def write_tokens(private_pem: str, client_id: str) -> Path:
    AUTH_DIR.mkdir(parents=True, exist_ok=True)
    out = AUTH_DIR / "tokens.json"
    people = {"A": SUB_A, "B": SUB_B}
    data = {name: {"sub": sub, "access": mint_token(private_pem, sub, client_id), "id": mint_token(private_pem, sub, client_id, token_use="id")}
            for name, sub in people.items()}
    data["client_id"] = client_id
    out.write_text(json.dumps(data), encoding="utf-8")
    return out


def main() -> None:
    if os.environ.get("CT_E2E") != "1":
        raise SystemExit("e2e: set CT_E2E=1 to start the test server (it is never started by accident).")
    port = int(os.environ.get("E2E_PORT", "8765"))
    workdir = tempfile.mkdtemp(prefix="ct-e2e-")
    safe = build_safe_env(dict(os.environ), workdir)
    assert_safe_env(safe)
    os.environ.clear()
    os.environ.update(safe)
    sys.path.insert(0, str(BACKEND))
    os.chdir(BACKEND)
    import db
    import models  # noqa: F401  registers the tables
    pem, jwk = make_keys()
    plant_keys(jwk)
    db.Base.metadata.create_all(db._get_engine())
    write_tokens(pem, safe["COGNITO_APP_CLIENT_ID"])
    import uvicorn
    uvicorn.run("main:app", host="127.0.0.1", port=port, log_level="warning")


if __name__ == "__main__":
    main()
