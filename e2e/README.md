# Browser and accessibility tests (N-06 foundation)

Local only. Fictional people, a stubbed sign-in, no AI. Nothing here can reach the production database, the Cognito tenant or the Anthropic API.

## How it is kept safe
1. `server/run_test_server.py` starts the app **only** when `CT_E2E=1`. It removes every real setting from the environment (database, AI key, Cognito, Turnstile, AWS, Render) and replaces them with local fakes: a throw-away SQLite file, a fake AI key that points at a closed local port (any AI call fails at once, on this machine), and a made-up sign-in pool whose key list is planted in memory (so no request ever leaves for Cognito). It checks the result (`assert_safe_env`) and stops if anything still looks real.
2. The browser fixture (`support/guard.js`) **aborts every request that is not to 127.0.0.1/localhost** (except the pinned read-only sign-in library on jsDelivr) and fails the test with the list, naming Cognito, Anthropic, Render, creatingtomorrow.net and AWS explicitly.
3. The Python suite (`backend/tests/test_e2e_guard.py`, runs in the normal CI) proves points 1 and 2's server half: a real-looking environment is scrubbed, each unsafe value is refused, the server will not start without `CT_E2E=1`, and the minted tokens work only for the planted key through the real token check.
4. Tokens for two fictional people (A, B) are written to `e2e/.auth/` (ignored by git). No password, cookie or real token is ever read or stored.
5. AI is never called: responses that a page needs are supplied by the test (`renderMatchReport(...)` with fixture data) or the step is not tested here. Live AI validation is a separate, explicitly approved activity.

## Run (after installing; installing downloads packages and browsers: needs approval)
```
cd e2e
npm install                      # @playwright/test and @axe-core/playwright, pinned
npx playwright install chromium  # or set E2E_CHANNEL=chrome / msedge to use the browser already on the computer
set CT_E2E=1                     # (PowerShell: $env:CT_E2E = "1")
npx playwright test --project=chromium
```
Projects: chromium, firefox, webkit, mobile-chromium (Pixel 5), mobile-webkit (iPhone SE). Mobile projects check layout only; real phones are still required for the file picker, downloads, keyboards and viewers.

## What is covered now
- `smoke.spec.js`: every public page loads, has a title and `lang`, throws no script errors, does not scroll sideways; security headers present.
- `a11y.spec.js`: axe-core (WCAG 2.2 AA tags) on every public page; **critical** violations fail, everything else is attached and listed as annotations until a baseline is agreed; one keyboard focus check.
- `security_xss.spec.js`: hostile strings through the real `renderMatchReport` and `renderQuestions` and the markdown renderer in a real browser (no script, no dialog, no injected elements).
- `auth_isolation.spec.js`: stubbed sign-in; no/garbage/ID token refused; A's record cannot be read, changed or deleted by B; a signed-in fictional person reaches the dashboard.

## Next steps (not done)
J1-J13 user journeys with mocked AI responses; tighten the axe baseline; resilience scenarios (slow network, offline, expired token, double submit, refresh); a CI job (a workflow change, needs approval) that runs this suite and, once stable, becomes a required check (a ruleset change, founder action).

## What cannot be automated
Real Safari, iOS and Android behaviour; downloads into phone viewers; Word/Google Docs rendering; screen-reader experience; whether a beginner understands the wording.
