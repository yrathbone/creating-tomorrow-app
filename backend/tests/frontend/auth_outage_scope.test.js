// Outage sign-out is scoped to this app's Cognito client. The client is the one last loaded in this tab (saved in the tab's
// session storage under "ct.cognito-app-client"). With no remembered client, nothing is cleared broadly. Runs the real
// frontend/career/js/auth.js in a bare VM with a stub SDK and a stub fetch. Nothing is sent anywhere.
const test = require("node:test");
const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const FRONTEND = path.join(__dirname, "..", "..", "..", "frontend", "career");
const AUTH_SOURCE = fs.readFileSync(path.join(FRONTEND, "js", "auth.js"), "utf8");
const CLIENT = "testclient123456";
const OTHER = "otherclient0000000";
const GOOD = { region: "us-east-2", user_pool_id: "us-east-2_TESTPOOL1", app_client_id: CLIENT };
const SDK = "CognitoIdentityServiceProvider.";
const REMEMBERED = "ct.cognito-app-client";

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

const jsonResponse = (status, body) => ({ ok: status >= 200 && status < 300, status, json: async () => body });
function fakeSession(access = "ACCESS-TOKEN") {
  return {
    isValid: () => true,
    getAccessToken: () => ({ getJwtToken: () => access }),
    getIdToken: () => ({ getJwtToken: () => "ID-TOKEN" }),
    getRefreshToken: () => ({ getToken: () => "REFRESH" }),
  };
}
function fakeCurrentUser(session) {
  return {
    getSession(cb) { cb(null, session); },
    signOut(cb) { cb(); },
    refreshSession(rt, cb) { cb(null, fakeSession("REFRESHED")); },
    deleteUser(cb) { cb(null); },
  };
}

// sessionItems / localItems: the tab's storage at the start. Reusing a previous run's _data simulates a page reload in the same tab.
function loadAuth(opts = {}) {
  const pools = [];
  class CognitoUserPool {
    constructor(o) { pools.push(o); }
    getCurrentUser() { return opts.currentUser || null; }
  }
  class CognitoUser {
    constructor(o) { this.o = o; }
    signOut(cb) { opts.signOutCalls = (opts.signOutCalls || 0) + 1; cb(); }
  }
  const storage = fakeStorage(opts.sessionItems || {});
  const local = fakeStorage(opts.localItems || {});
  const fetchCalls = [];
  const sandbox = {
    window: { sessionStorage: storage, localStorage: local },
    AmazonCognitoIdentity: {
      CognitoUserPool, CognitoUser,
      AuthenticationDetails: class {},
      CognitoUserAttribute: class {},
    },
    fetch: (url) => { fetchCalls.push(url); return opts.fetch(url); },
  };
  vm.createContext(sandbox);
  vm.runInContext(AUTH_SOURCE, sandbox);
  return { sandbox, pools, storage, local, fetchCalls };
}

const unavailable = () => () => Promise.resolve(jsonResponse(503, {}));
const available = () => () => Promise.resolve(jsonResponse(200, GOOD));
const never = () => () => new Promise(() => {});

test("a successful load remembers this app client in the tab's session storage", async () => {
  const w = loadAuth({ fetch: available() });
  await w.sandbox.ensureAuthReady();
  assert.strictEqual(w.storage._data[REMEMBERED], CLIENT);
});

test("outage sign-out with no remembered client clears nothing broadly: other clients' and own keys are kept", async () => {
  const own = SDK + CLIENT + ".LastAuthUser";
  const other = SDK + OTHER + ".LastAuthUser";
  const w = loadAuth({
    fetch: never(),
    currentUser: fakeCurrentUser(fakeSession()),
    sessionItems: { [own]: "member", [other]: "someone-else", "ct.unrelated": "keep" },
    localItems: { [other + "x"]: "keep-local", [SDK + CLIENT + ".idToken"]: "old-local" },
  });
  await w.sandbox.signOutCurrentUser();
  assert.strictEqual(w.storage._data[own], "member", "no remembered client: this client's key is not removed blindly");
  assert.strictEqual(w.storage._data[other], "someone-else");
  assert.strictEqual(w.local._data[SDK + CLIENT + ".idToken"], "old-local");
  assert.strictEqual(w.storage._data["ct.unrelated"], "keep");
});

test("outage sign-out removes only the remembered client's keys, in session and local storage, and touches no other client", async () => {
  const own = SDK + CLIENT + ".LastAuthUser";
  const other = SDK + OTHER + ".LastAuthUser";
  const w = loadAuth({
    fetch: never(),
    sessionItems: { [REMEMBERED]: CLIENT, [own]: "member", [SDK + CLIENT + ".idToken"]: "id", [other]: "someone-else", "ct.auth-notice": "notice" },
    localItems: { [SDK + CLIENT + ".LastAuthUser"]: "old", [SDK + OTHER + ".LastAuthUser"]: "keep-local", unrelated: "keep" },
  });
  await w.sandbox.signOutCurrentUser();
  assert.strictEqual(w.storage._data[own], undefined, "this client's marker is removed at once");
  assert.strictEqual(w.storage._data[SDK + CLIENT + ".idToken"], undefined, "this client's tokens are removed at once");
  assert.strictEqual(w.local._data[SDK + CLIENT + ".LastAuthUser"], undefined, "this client's leftover local copy is removed");
  assert.strictEqual(w.storage._data[other], "someone-else", "another client's key is kept");
  assert.strictEqual(w.local._data[SDK + OTHER + ".LastAuthUser"], "keep-local", "another client's local key is kept");
  assert.strictEqual(w.storage._data["ct.auth-notice"], "notice", "the sign-in notice is kept");
  assert.strictEqual(w.local._data.unrelated, "keep", "unrelated local storage is kept");
  assert.strictEqual(w.storage._data[REMEMBERED], CLIENT, "the remembered client itself is kept for the next outage");
});

test("the remembered client survives a page reload in the same tab, so an outage sign-out after the reload is still scoped", async () => {
  const first = loadAuth({ fetch: available() });
  await first.sandbox.ensureAuthReady();                       // the tab loads the configuration and remembers the client
  const after = Object.assign({}, first.storage._data, { [SDK + CLIENT + ".idToken"]: "id", [SDK + OTHER + ".idToken"]: "keep" });
  const reloaded = loadAuth({ fetch: never(), sessionItems: after });   // reload: configuration unavailable now
  await reloaded.sandbox.signOutCurrentUser();
  assert.strictEqual(reloaded.storage._data[SDK + CLIENT + ".idToken"], undefined);
  assert.strictEqual(reloaded.storage._data[SDK + OTHER + ".idToken"], "keep");
});

test("a malformed remembered value is ignored: nothing is removed", async () => {
  const w = loadAuth({
    fetch: never(),
    sessionItems: { [REMEMBERED]: "not a client id!", [SDK + "not a client id!.idToken"]: "x" },
  });
  await w.sandbox.signOutCurrentUser();
  assert.strictEqual(w.storage._data[SDK + "not a client id!.idToken"], "x");
});

test("automatic configuration failure keeps this client's session when a client is remembered", async () => {
  const key = SDK + CLIENT + ".LastAuthUser";
  const w = loadAuth({
    fetch: unavailable(),
    currentUser: fakeCurrentUser(fakeSession("STILL-VALID")),
    sessionItems: { [REMEMBERED]: CLIENT, [key]: "member", [SDK + CLIENT + ".idToken"]: "id" },
  });
  await assert.rejects(w.sandbox.getValidSession(), (err) => err.code === "AuthUnavailable");
  assert.strictEqual(w.storage._data[key], "member", "a failed automatic restore must not remove the session");
  assert.strictEqual(w.storage._data[SDK + CLIENT + ".idToken"], "id");
});

test("signed-in sign-out clears only this client's keys after the SDK signs out, and keeps other clients' keys", async () => {
  const w = loadAuth({
    fetch: available(),
    currentUser: fakeCurrentUser(fakeSession()),
    sessionItems: { [SDK + CLIENT + ".LastAuthUser"]: "member", [SDK + OTHER + ".LastAuthUser"]: "keep", "ct.unrelated": "keep" },
  });
  await w.sandbox.ensureAuthReady();
  await w.sandbox.signOutCurrentUser();
  assert.strictEqual(w.storage._data[SDK + CLIENT + ".LastAuthUser"], undefined);
  assert.strictEqual(w.storage._data[SDK + OTHER + ".LastAuthUser"], "keep");
  assert.strictEqual(w.storage._data["ct.unrelated"], "keep");
});

test("the outage path needs no network and no configuration to run", async () => {
  const w = loadAuth({ fetch: () => { throw new Error("must not be called"); }, sessionItems: { [REMEMBERED]: CLIENT, [SDK + CLIENT + ".idToken"]: "id" } });
  await w.sandbox.signOutCurrentUser();
  assert.strictEqual(w.fetchCalls.length, 0);
  assert.strictEqual(w.storage._data[SDK + CLIENT + ".idToken"], undefined);
});
