// frontend/auth-nav.js (public pages' header): uses the same remembered app client as auth.js, not a hard-coded one. Runs the
// real file in a bare VM with stub storage and a stub DOM. Nothing is sent anywhere.
const test = require("node:test");
const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const FRONTEND = path.join(__dirname, "..", "..", "..", "frontend");
const NAV_SOURCE = fs.readFileSync(path.join(FRONTEND, "auth-nav.js"), "utf8");
const CLIENT = "testclient123456";
const OTHER = "otherclient0000000";
const SDK = "CognitoIdentityServiceProvider.";

function fakeStorage(initial = {}) {
  const data = Object.assign({}, initial);
  return {
    _data: data,
    get length() { return Object.keys(data).length; },
    key(i) { const k = Object.keys(data)[i]; return k === undefined ? null : k; },
    getItem(k) { return Object.prototype.hasOwnProperty.call(data, k) ? data[k] : null; },
    setItem(k, v) { data[k] = String(v); },
    removeItem(k) { delete data[k]; },
  };
}

function run({ session = {}, local = {} }) {
  const navLinks = [{ textContent: "Sign In" }, { textContent: "Sign In" }];
  const head = { appended: [], appendChild(el) { this.appended.push(el); } };
  const sessionStore = fakeStorage(session);
  const localStore = fakeStorage(local);
  const sandbox = {
    window: { sessionStorage: sessionStore, localStorage: localStore },
    document: {
      head,
      querySelectorAll(sel) { return sel === "a.nav-account" ? navLinks : []; },
      createElement() { return { textContent: "" }; },
    },
  };
  vm.createContext(sandbox);
  vm.runInContext(NAV_SOURCE, sandbox);
  return { navLinks, head, sessionStore, localStore };
}

test("auth-nav.js does not contain a hard-coded production client id", () => {
  assert.ok(!NAV_SOURCE.includes("5rfhr0o7799aa41a5odrt9i9hd"), "the production client id must not be hard-coded");
  assert.ok(!NAV_SOURCE.includes("uLhNvjpep"), "the production pool id must not be hard-coded");
});

test("with no remembered client, auth-nav removes no Cognito keys and changes no label", () => {
  const r = run({ local: { [SDK + CLIENT + ".LastAuthUser"]: "old", [SDK + OTHER + ".LastAuthUser"]: "keep" } });
  assert.strictEqual(r.localStore._data[SDK + CLIENT + ".LastAuthUser"], "old", "nothing is guessed when no client is remembered");
  assert.strictEqual(r.localStore._data[SDK + OTHER + ".LastAuthUser"], "keep");
  assert.deepStrictEqual(r.navLinks.map((l) => l.textContent), ["Sign In", "Sign In"]);
});

test("with a remembered client, auth-nav removes only that client's leftover local keys", () => {
  const r = run({
    session: { "ct.cognito-app-client": CLIENT },
    local: { [SDK + CLIENT + ".LastAuthUser"]: "old", [SDK + OTHER + ".LastAuthUser"]: "keep", unrelated: "keep" },
  });
  assert.strictEqual(r.localStore._data[SDK + CLIENT + ".LastAuthUser"], undefined);
  assert.strictEqual(r.localStore._data[SDK + OTHER + ".LastAuthUser"], "keep", "another client's key is kept");
  assert.strictEqual(r.localStore._data.unrelated, "keep");
});

test("with a remembered client and a live session in this tab, the header says My Career and the homepage prompt is hidden", () => {
  const r = run({
    session: {
      "ct.cognito-app-client": CLIENT,
      [SDK + CLIENT + ".LastAuthUser"]: "member",
      [SDK + CLIENT + ".member.refreshToken"]: "token",
    },
  });
  assert.deepStrictEqual(r.navLinks.map((l) => l.textContent), ["My Career", "My Career"]);
  assert.strictEqual(r.head.appended.length, 1, "the hide rule is added once");
});

test("a live session for another client does not change the header", () => {
  const r = run({
    session: {
      "ct.cognito-app-client": CLIENT,
      [SDK + OTHER + ".LastAuthUser"]: "someone-else",
      [SDK + OTHER + "someone-else.refreshToken"]: "token",
    },
  });
  assert.deepStrictEqual(r.navLinks.map((l) => l.textContent), ["Sign In", "Sign In"]);
});

test("a malformed remembered value is ignored", () => {
  const r = run({ session: { "ct.cognito-app-client": "bad value!" }, local: { [SDK + "bad value!.LastAuthUser"]: "x" } });
  assert.strictEqual(r.localStore._data[SDK + "bad value!.LastAuthUser"], "x");
  assert.deepStrictEqual(r.navLinks.map((l) => l.textContent), ["Sign In", "Sign In"]);
});
