// Playwright configuration (N-06). Local only: the server is started by server/run_test_server.py, which removes every real setting and
// refuses to run unless CT_E2E=1. The `guard` fixture (support/guard.js) additionally blocks every request that is not to this machine.
const { defineConfig, devices } = require("@playwright/test");

const PORT = process.env.E2E_PORT || "8765";
// Optional: use the browser already installed on this computer instead of downloading one (E2E_CHANNEL=chrome or msedge).
const channel = process.env.E2E_CHANNEL || undefined;
// Browser-level guard (Chromium): every host name except this machine and the pinned sign-in CDN fails to resolve, for pages, workers, redirects and
// WebSockets alike. It is independent of the per-request guard in support/guard.js (two layers).
const CHROMIUM_ARGS = ["--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE 127.0.0.1, EXCLUDE localhost, EXCLUDE cdn.jsdelivr.net"];

module.exports = defineConfig({
  testDir: "./specs",
  timeout: 30_000,
  expect: { timeout: 5_000 },
  fullyParallel: false,
  workers: 1,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [["github"], ["html", { open: "never" }]] : [["list"], ["html", { open: "never" }]],
  use: {
    baseURL: `http://127.0.0.1:${PORT}`,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    serviceWorkers: "block",
  },
  webServer: {
    command: "python server/run_test_server.py",
    url: `http://127.0.0.1:${PORT}/api/health`,
    env: { CT_E2E: "1", E2E_PORT: PORT },
    reuseExistingServer: false,
    timeout: 60_000,
  },
  projects: [
    { name: "chromium", use: { ...devices["Desktop Chrome"], channel, launchOptions: { args: CHROMIUM_ARGS } } },
    { name: "firefox", use: { ...devices["Desktop Firefox"] } },
    { name: "webkit", use: { ...devices["Desktop Safari"] } },
    // Layout and touch-target checks only. Real iPhone and Android behaviour (file picker, downloads, keyboards) needs real devices.
    { name: "mobile-chromium", use: { ...devices["Pixel 5"], channel, launchOptions: { args: CHROMIUM_ARGS } } },
    { name: "mobile-webkit", use: { ...devices["iPhone SE"] } },
  ],
});
