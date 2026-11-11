"""Localhost-only signed-in test harness for the browser workflow (C-52 F08).

What it does
- Starts the REAL application (main.app) on 127.0.0.1 against a fresh SQLite database in a scratch folder.
- Verifies tokens with the REAL code path (auth/dependencies.py): RS256 signature, issuer, expiry, token_use, client_id.
  The only substitution is the public key list: a key generated when the harness starts, held in memory, never written to disk.
- Creates two SYNTHETIC members with profiles and one synthetic résumé each. No real data.
- Serves a sign-in helper page (/__harness/signin) that stores a freshly minted test session in the browser tab, the way the
  Cognito SDK would, then opens the sign-in page. Token lifetime is configurable so expired-session behaviour can be tested.
- Replaces only the two Cognito identifiers in the served js/auth.js with the harness identifiers. The file on disk is unchanged.

What it refuses to do
- Run unless CT_LOCAL_HARNESS=1 is set in the environment.
- Run on any host other than 127.0.0.1.
- Run when any hosting-platform marker is present (RENDER, RENDER_SERVICE_ID, RENDER_EXTERNAL_URL) or when CT_ENV is production.
- Use or contact Amazon Cognito. Production identifiers never leave the file on disk.

Usage (from the backend folder; never in production):
  set CT_LOCAL_HARNESS=1
  python tests/harness/local_signed_in.py --port 8765 --workdir <scratch folder>
"""
import argparse
import base64
import json
import os
import pathlib
import sqlite3
import sys
import time

BACKEND = pathlib.Path(__file__).resolve().parents[2]
REGION = "us-east-2"
POOL = "us-east-2_LOCALHARNESS"
CLIENT = "localharnessclient000000000000"
ISSUER = f"https://cognito-idp.{REGION}.amazonaws.com/{POOL}"
KID = "local-harness-kid"
PROD_POOL = "us-east-2_uLhNvjpep"       # the identifiers in frontend/career/js/auth.js (replaced in the served copy only)
PROD_CLIENT = "5rfhr0o7799aa41a5odrt9i9hd"
MEMBERS = {"a": "synthetic-member-a", "b": "synthetic-member-b"}


def guard(host: str) -> None:
    if os.environ.get("CT_LOCAL_HARNESS") != "1":
        raise SystemExit("Refused: set CT_LOCAL_HARNESS=1 to run the local test harness.")
    if host != "127.0.0.1":
        raise SystemExit("Refused: the harness only listens on 127.0.0.1.")
    for marker in ("RENDER", "RENDER_SERVICE_ID", "RENDER_EXTERNAL_URL"):
        if os.environ.get(marker):
            raise SystemExit("Refused: a hosting-platform marker is present; the harness never runs there.")
    if os.environ.get("CT_ENV", "").lower() == "production":
        raise SystemExit("Refused: CT_ENV is production.")


def make_key():
    from cryptography.hazmat.primitives.asymmetric import rsa
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def public_jwk(key):
    from jwt.algorithms import RSAAlgorithm
    jwk = json.loads(RSAAlgorithm.to_jwk(key.public_key()))
    jwk.update({"kid": KID, "use": "sig", "alg": "RS256"})
    return jwk


def mint(key, sub: str, token_use: str, ttl: int):
    import jwt
    now = int(time.time())
    claims = {"iss": ISSUER, "sub": sub, "token_use": token_use, "iat": now, "exp": now + ttl, "username": sub}
    if token_use == "access":
        claims["client_id"] = CLIENT
        claims["scope"] = "openid"
    else:
        claims["aud"] = CLIENT
        claims["cognito:username"] = sub
    return jwt.encode(claims, key, algorithm="RS256", headers={"kid": KID})


def seed(db_path: pathlib.Path) -> None:
    """Migrations (real alembic chain) and two synthetic members, each with a profile and one résumé."""
    import subprocess
    env = dict(os.environ, DATABASE_URL="sqlite:///" + db_path.as_posix())
    subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=BACKEND, env=env, check=True)
    con = sqlite3.connect(db_path)
    for i, sub in enumerate(MEMBERS.values(), start=1):
        con.execute("insert into users (cognito_sub) values (?)", (sub,))
        uid = con.execute("select id from users where cognito_sub=?", (sub,)).fetchone()[0]
        con.execute("insert into career_profiles (user_id) values (?)", (uid,))
        pid = con.execute("select id from career_profiles where user_id=?", (uid,)).fetchone()[0]
        data = json.dumps({"name": f"Synthetic Member {'AB'[i-1]}", "summary": "Synthetic test résumé.", "contact": "test@example.invalid"})
        con.execute("insert into resume_versions (career_profile_id, resume_data) values (?, ?)", (pid, data))
    con.commit()
    con.close()


def build_app(db_path: pathlib.Path, key):
    os.environ["DATABASE_URL"] = "sqlite:///" + db_path.as_posix()
    os.environ["CT_OPPORTUNITIES_ENABLED"] = "1"
    os.environ["COGNITO_REGION"] = REGION
    os.environ["COGNITO_USER_POOL_ID"] = POOL
    os.environ["COGNITO_APP_CLIENT_ID"] = CLIENT
    sys.path.insert(0, str(BACKEND))
    import time as _t
    import auth.dependencies as deps
    deps._jwks_cache = {"keys": [public_jwk(key)]}          # the only substitution: the public key list
    deps._jwks_fetched_at = None
    deps._jwks_last_attempt = _t.monotonic()
    from fastapi.responses import HTMLResponse, Response
    from starlette.routing import Route
    import main

    frontend = BACKEND.parent / "frontend"

    async def signin(request):
        member = request.query_params.get("member", "a")
        ttl = int(request.query_params.get("ttl", "3600"))
        if member not in MEMBERS:
            return HTMLResponse("unknown synthetic member", status_code=404)
        sub = MEMBERS[member]
        access = mint(key, sub, "access", ttl)
        idt = mint(key, sub, "id", ttl)
        pre = f"CognitoIdentityServiceProvider.{CLIENT}."
        keys = {pre + "LastAuthUser": sub, pre + sub + ".idToken": idt, pre + sub + ".accessToken": access,
                pre + sub + ".refreshToken": "harness-refresh-not-real", pre + sub + ".clockDrift": "0"}
        page = ("<!doctype html><meta charset=utf-8><title>Test sign-in</title><p>Signing in a synthetic test member...</p>"
                "<script>var k=" + json.dumps(keys) + ";"
                "try{for(var i=sessionStorage.length-1;i>=0;i--){var n=sessionStorage.key(i);if(n.indexOf('CognitoIdentityServiceProvider.')===0)sessionStorage.removeItem(n);}"
                "for(var n in k){sessionStorage.setItem(n,k[n]);}}catch(e){document.body.append('storage unavailable');}"
                "location.replace('/career/login.html');</script>")
        return HTMLResponse(page, headers={"Cache-Control": "no-store"})

    async def auth_js(request):
        text = (frontend / "career" / "js" / "auth.js").read_text(encoding="utf-8")
        text = text.replace(f'"{PROD_POOL}"', f'"{POOL}"').replace(f'"{PROD_CLIENT}"', f'"{CLIENT}"')
        return Response(text, media_type="application/javascript", headers={"Cache-Control": "no-store"})

    async def not_found_harness(request):
        return HTMLResponse("not available", status_code=404)

    harness_routes = [
        Route("/__harness/signin", signin),
        Route("/career/js/auth.js", auth_js),
    ]
    main.app.router.routes[0:0] = harness_routes    # ahead of the static mount, so these two paths are served by the harness
    return main.app


def main_cli() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--workdir", required=True)
    ap.add_argument("--host", default="127.0.0.1")
    args = ap.parse_args()
    guard(args.host)
    work = pathlib.Path(args.workdir)
    work.mkdir(parents=True, exist_ok=True)
    db_path = work / "harness.sqlite"
    if db_path.exists():
        db_path.unlink()
    seed(db_path)
    key = make_key()
    app = build_app(db_path, key)
    import uvicorn
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main_cli()
