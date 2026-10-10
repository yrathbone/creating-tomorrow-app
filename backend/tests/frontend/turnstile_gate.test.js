// Runs frontend/turnstile-gate.js against a fake browser to prove: it is invisible when the check is off, it attaches a fresh
// single-use pass to exactly the nine AI calls when on, and it never touches any other request.
const test = require("node:test");
const assert = require("node:assert");
const fs = require("fs");
const path = require("path");
const vm = require("vm");

const SRC = fs.readFileSync(path.join(__dirname, "..", "..", "..", "frontend", "turnstile-gate.js"), "utf8");
const AI = ["/api/analyze", "/api/refine", "/api/elevate-start", "/api/elevate-discover", "/api/elevate-finalize", "/api/profile-review", "/api/prepare", "/api/scratch-entry", "/api/scratch-finalize"];

function browser(config) {
  const calls = [];
  const injected = [];
  const resets = [];
  let renderOptions = null;
  const win = {
    location: { href: "https://creatingtomorrow.net/tool.html" },
    fetch: async (url, init) => {
      calls.push({ url: String(url), init });
      if (String(url).startsWith("/api/turnstile-config")) return { ok: true, json: async () => config };
      return { ok: true, status: 200, json: async () => ({}) };
    },
  };
  const doc = {
    body: { appendChild: (el) => injected.push(el) },
    head: { appendChild: (el) => { injected.push(el); if (el.src && el.onload) setTimeout(() => { win.turnstile = { render: (box, opts) => { renderOptions = opts; return "w1"; }, reset: (id) => resets.push(id) }; el.onload(); }, 0); } },
    createElement: (tag) => ({ tag, style: {}, set src(v) { this._src = v; }, get src() { return this._src; } }),
    addEventListener: () => {},
  };
  const ctx = { window: win, document: doc, URL, Headers, Promise, setTimeout, clearTimeout, Object, console };
  win.window = win;
  vm.createContext(ctx);
  vm.runInContext(SRC, ctx);
  return { win, calls, injected, resets, options: () => renderOptions };
}

const tick = (ms = 20) => new Promise((r) => setTimeout(r, ms));
const headerOf = (call) => (call.init && call.init.headers && call.init.headers.get ? call.init.headers.get("X-Turnstile-Token") : null);

test("when the check is off nothing changes: no Cloudflare script, no header, same fetch behaviour", async () => {
  const b = browser({ enabled: false, site_key: null });
  await b.win.fetch("/api/analyze", { method: "POST", body: "x" });
  assert.strictEqual(b.injected.length, 0, "no script and no widget box are added");
  const call = b.calls.find((c) => c.url === "/api/analyze");
  assert.strictEqual(headerOf(call), null);
});

test("when on, Cloudflare's script is loaded once with the public site key and an interaction-only widget", async () => {
  const b = browser({ enabled: true, site_key: "0x4AAAAAAApublic" });
  await tick();
  const script = b.injected.find((e) => e.tag === "script");
  assert.ok(script && script.src.startsWith("https://challenges.cloudflare.com/turnstile/v0/api.js"));
  assert.strictEqual(b.options().sitekey, "0x4AAAAAAApublic");
  assert.strictEqual(b.options().appearance, "interaction-only");
});

test("every one of the nine AI calls carries the pass, and a new pass is requested after each use", async () => {
  const b = browser({ enabled: true, site_key: "0x4AAAAAAApublic" });
  await tick();
  for (const [i, p] of AI.entries()) {
    b.options().callback("token-" + i);
    await b.win.fetch(p, { method: "POST", body: "data" });
    await tick(5);
    const call = b.calls.filter((c) => c.url === p).pop();
    assert.strictEqual(headerOf(call), "token-" + i, p);
  }
  assert.strictEqual(b.resets.length, AI.length, "the widget is reset after each use (a pass works once)");
});

test("other requests are never touched: other paths, GETs, and uploads keep their own headers", async () => {
  const b = browser({ enabled: true, site_key: "0x4AAAAAAApublic" });
  await tick();
  b.options().callback("t");
  await b.win.fetch("/api/health", { method: "GET" });
  await b.win.fetch("/api/career/me", { method: "POST", headers: { Authorization: "Bearer x" } });
  await b.win.fetch("/api/analyze", { method: "GET" });
  for (const c of b.calls.filter((c) => !c.url.startsWith("/api/turnstile-config"))) assert.strictEqual(headerOf(c), null, c.url);
  await b.win.fetch("/api/prepare", { method: "POST", headers: { "X-Other": "kept" }, body: "x" });
  const call = b.calls.filter((c) => c.url === "/api/prepare").pop();
  assert.strictEqual(call.init.headers.get("X-Other"), "kept");
  assert.strictEqual(call.init.headers.get("X-Turnstile-Token"), "t");
});

test("an expired pass is dropped, and a click waits for the next pass instead of sending an old one", async () => {
  const b = browser({ enabled: true, site_key: "0x4AAAAAAApublic" });
  await tick();
  b.options().callback("old");
  b.options()["expired-callback"]();
  const pending = b.win.fetch("/api/refine", { method: "POST", body: "x" });
  await tick(10);
  assert.strictEqual(b.calls.filter((c) => c.url === "/api/refine").length, 0, "still waiting for a fresh pass");
  b.options().callback("fresh");
  await pending;
  assert.strictEqual(headerOf(b.calls.filter((c) => c.url === "/api/refine").pop()), "fresh");
});
