# Cross-browser and device plan (E1; plan only, nothing downloaded or run)

Status 2026-11-07: Chromium (system Chrome) and mobile Chromium run locally and pass. Firefox, WebKit and mobile WebKit are defined in `playwright.config.js` but have **not** been run: they need `npx playwright install firefox webkit`, a browser download that needs its own approval (assumed a few hundred MB; confirm the size when approved).

## Phases
| Phase | Scope | Needs |
|---|---|---|
| 1 (done) | Chromium + mobile Chromium: smoke, axe baseline, sign-in keyboard and focus, 320 px reflow, isolation, XSS | nothing |
| 2 | Firefox and WebKit locally: smoke, axe baseline, sign-in keyboard (Safari does not Tab to links by default, so the keyboard test is skipped on WebKit), reflow | approval to download browsers; the egress guard below |
| 3 | CI job (separate PR): Chromium required-after-reliability, Firefox/WebKit non-required nightly | push approval; CI change approval |
| 4 | Real devices and assistive technology (manual): iPhone Safari, Android Chrome, NVDA + Firefox/Chrome, VoiceOver + Safari; Word/Google Docs downloads | the founder or a tester with devices |

## Network containment for non-Chromium browsers
Chromium has `--host-resolver-rules` (blocks every name but localhost). Firefox and WebKit do not. Layers that remain: the per-request guard in `support/guard.js` (fails any test that requests a non-local host), the scrubbed server environment, and the dead outbound proxy. Before Phase 2 add a browser-level layer for Firefox (`firefoxUserPrefs` pointing the proxy at a closed local port and `network.proxy.no_proxies_on` limited to localhost) and verify it with the existing guard self-tests (a redirect to a real host must not connect). WebKit: rely on the guard plus the host firewall rule if the founder wants one.

## Expected differences to anticipate
Safari/WebKit: link Tab-stop behaviour, date/time inputs, `autocomplete` handling, stricter cookie/storage rules (sessionStorage stub sign-in should work). Firefox: focus-ring defaults, `:has()` support differences. Mobile WebKit: viewport units and the keyboard overlay; the file picker cannot be automated.

## Exit criteria for "cross-browser covered"
All specs pass on the five projects with zero guard violations; any failures are fixed or recorded as known findings with `test.fail()` and an owner; the manual device/assistive-technology checklist has been run once and its results recorded in the Command Center.

## Known findings from E1 (so far)
- E1-F1 (Medium-Low): after "Back to sign in" keyboard focus falls to `<body>` (WCAG 2.4.3). Recorded as an expected failure in `specs/a11y_login.spec.js`.
- E1-F2 (Low): "Forgot your password?" is 22 px high; allowed only by the spacing exception of WCAG 2.5.8; consider 24 px.
- E1-F3 (Medium, matrix U-03): footer brand gold on white is 2.22:1 (needs 3:1 for large bold text); on the dashboard `.next-step-eyebrow` 4.44:1, `#cp-name` and `#cp-contact` 3.79:1 (need 4.5:1). Baselined in `support/axe_baseline.json` so any new violation fails. Footer amber is a founder brand decision.
