# Browser and accessibility tests (N-06 foundation)

Local only. Fictional people, a stubbed sign-in, no AI. Nothing here can reach the production database, the Cognito tenant or the Anthropic API.

## How it is kept safe
1. `server/run_test_server.py` starts the app **only** when `CT_E2E=1`. It removes every real setting from the environment (database, AI key, Cognito, Turnstile, AWS, Render) and replaces them with local fakes: a throw-away SQLite file, a fake AI key that points at a closed local port (any AI call fails at once, on this machine), and a made-up sign-in pool whose key list is planted in memory (so no request ever leaves for Cognito). It checks the result (`assert_safe_env`) and stops if anything still looks real.
2. The browser fixture (`support/guard.js`) **aborts every request that is not to 127.0.0.1/localhost** (except the pinned read-only sign-in library on jsDelivr) and fails the test with the list, naming Cognito, Anthropic, Render, creatingtomorrow.net and AWS explicitly.
3. The Python suite (`backend/tests/test_e2e_guard.py`, runs in the normal CI) proves points 1 and 2's server half: a real-looking environment is scrubbed, each unsafe value is refused, the server will not start without `CT_E2E=1`, and the minted tokens work only for the planted key through the real token check.
4. Tokens for two fictional people (A, B) are written to `e2e/.auth/` (ignored by git). No password, cookie or real token is ever read or stored.
5. AI is never called: responses that a page needs are supplied by the test (`renderMatchReport(...)` with fixture data) or the step is not tested here. Live AI validation is a separate, explicitly approved activity.

## Run
```
cd e2e
npm ci --ignore-scripts          # installs the exact pinned packages from package-lock.json; no install scripts run
set CT_E2E=1                     # (PowerShell: $env:CT_E2E = "1")
set E2E_CHANNEL=chrome           # use the Chrome already on the computer: no browser download (PowerShell: $env:E2E_CHANNEL = "chrome")
npx playwright test --project=chromium --project=mobile-chromium
```
Firefox and WebKit projects are defined but need `npx playwright install firefox webkit` (a browser download that needs separate approval); they have NOT been run. Their per-request guard works, but the browser-level host-name block below is configured for Chromium only.

Layers that keep the tests local: (1) the server launcher scrubs the environment, uses fake AI/Cognito/database settings and a dead local proxy for outbound calls; (2) the browser blocks every host name except 127.0.0.1, localhost and the pinned sign-in library CDN (Chromium `--host-resolver-rules`); (3) the per-request guard aborts and records anything else and fails the test (self-tests in `specs/guard_selftest.spec.js` prove it). The only external requests are GETs for the pinned, integrity-checked sign-in library on cdn.jsdelivr.net: no tokens, cookies or test data are sent.

## What is covered now
- `smoke.spec.js`: every public page loads, has a title and `lang`, throws no script errors, does not scroll sideways; security headers present.
- `a11y.spec.js`: axe-core (WCAG 2.2 AA tags) on every public page; **critical** violations fail, everything else is attached and listed as annotations until a baseline is agreed; one keyboard focus check.
- `security_xss.spec.js`: hostile strings through the real `renderMatchReport` and `renderQuestions` and the markdown renderer in a real browser (no script, no dialog, no injected elements).
- `auth_isolation.spec.js`: stubbed sign-in; no/garbage/ID token refused; A's record cannot be read, changed or deleted by B; a signed-in fictional person reaches the dashboard, and a signed-out visitor does not.
- `guard_selftest.spec.js`: the guard fails any test that reaches for Anthropic or Cognito; a redirect to a real service does not connect.

## Next steps (not done)
J1-J13 user journeys with mocked AI responses; tighten the axe baseline; resilience scenarios (slow network, offline, expired token, double submit, refresh); a CI job (a workflow change, needs approval) that runs this suite and, once stable, becomes a required check (a ruleset change, founder action).

## What cannot be automated
Real Safari, iOS and Android behaviour; downloads into phone viewers; Word/Google Docs rendering; screen-reader experience; whether a beginner understands the wording.
