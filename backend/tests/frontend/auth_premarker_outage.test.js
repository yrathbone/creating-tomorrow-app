// Explicit sign-out during a configuration outage must not be undone when the configuration recovers. This covers a tab whose
// SDK sign-in keys were written BEFORE the remembered-client marker ("ct.cognito-app-client") existed, and so has no remembered
// client. The sign-out is remembered ("ct.signed-out-pending") and applied when the configuration loads.
// Runs the real frontend/career/js/auth.js in a bare VM with a stub SDK and a stub fetch. Nothing is sent anywhere.
// The stub SDK behaves like the real one on the points that matter here: getCurrentUser returns a user only while this app
// client's LastAuthUser key is present in the session storage.
const test = require("node:test");
const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const FRONTEND = path.join(__dirname, "..", "..", "..", "frontend", "career");
const AUTH_SOURCE = fs.readFileSync(path.join(FRONTEND, "js", "auth.js"), "utf8");
const CLIENT = "testclient123456";
const SDK = "CognitoIdentityServiceProvider.";
const LAST_USER = SDK + CLIENT + ".LastAuthUser";
const PENDING = "ct.signed-out-pending";
const GOOD = { region: "us-east-2", user_pool_id: "us-east-2_TESTPOOL1", app_client_id: CLIENT };

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
function fakeSession(access) {
  return {
    isValid: () => true,
    getAccessToken: () => ({ getJwtToken: () => access }),
    getIdToken: () => ({ getJwtToken: () => "ID" }),
    getRefreshToken: () => ({ getToken: () => "REFRESH" }),
  };
}
const outage = () => () => Promise.resolve(jsonResponse(503, {}));

// session: the session the SDK would hand back for the saved sign-in (used only while LAST_USER is present).
function load({ fetch, session, sessionItems, localItems = {} }) {
  const storage = fakeStorage(sessionItems);
  const local = fakeStorage(localItems);
  class CognitoUserPool {
    constructor() {}
    getCurrentUser() {
      if (!storage.getItem(LAST_USER) || !session) return null;
      return {
        getSession(cb) { cb(null, session); },
        signOut(cb) { cb(); },
        refreshSession(rt, cb) { cb(null, session); },
      };
    }
  }
  class CognitoUser {
    constructor() {}
    authenticateUser(details, cbs) {
      storage.setItem(LAST_USER, details.d.Username);            // the SDK records who signed in
      cbs.onSuccess(fakeSession("NEW-SIGN-IN-TOKEN"));
    }
  }
  const sandbox = {
    window: { sessionStorage: storage, localStorage: local },
    AmazonCognitoIdentity: {
      CognitoUserPool, CognitoUser,
      AuthenticationDetails: class { constructor(d) { this.d = d; } },
      CognitoUserAttribute: class {},
    },
    fetch,
  };
  vm.createContext(sandbox);
  vm.runInContext(AUTH_SOURCE, sandbox);
  return { sandbox, storage, local };
}

const PRE_MARKER = {
  [LAST_USER]: "member@example.invalid",
  [SDK + CLIENT + ".member@example.invalid.idToken"]: "id",
};

test("pre-marker tab: the tab holds SDK keys and no remembered client", () => {
  const w = load({ fetch: outage(), session: fakeSession("OLD"), sessionItems: { ...PRE_MARKER } });
  assert.strictEqual(w.storage._data["ct.cognito-app-client"], undefined);
  assert.strictEqual(w.sandbox.hasStoredSessionKeys(), false, "before the configuration loads, the local check cannot find the key");
});

test("pre-marker tab, explicit sign-out during an outage: the sign-out is remembered and the keys are kept until the configuration loads", async () => {
  const w = load({ fetch: outage(), session: fakeSession("OLD"), sessionItems: { ...PRE_MARKER } });
  await w.sandbox.signOutCurrentUser();
  assert.strictEqual(w.storage._data[PENDING], "1", "the sign-out is remembered in this tab");
  assert.strictEqual(w.storage._data[LAST_USER], "member@example.invalid", "the keys cannot be named before the configuration loads");
});

test("pre-marker tab: after the configuration recovers, the signed-out session is NOT restored", async () => {
  let attempt = 0;
  const w = load({
    fetch: () => { attempt += 1; return Promise.resolve(attempt === 1 ? jsonResponse(503, {}) : jsonResponse(200, GOOD)); },
    session: fakeSession("OLD-SESSION-TOKEN"),
    sessionItems: { ...PRE_MARKER },
  });
  await assert.rejects(w.sandbox.ensureAuthReady(), (err) => err.code === "AuthUnavailable");   // the outage, as the page sees it
  await w.sandbox.signOutCurrentUser();                                                          // Sign Out during the outage
  assert.strictEqual(await w.sandbox.retryAuthConfig(), true, "the configuration recovers (the page's Try again)");
  assert.strictEqual(w.storage._data[LAST_USER], undefined, "this tab's sign-in marker is removed on recovery");
  assert.strictEqual(w.storage._data[SDK + CLIENT + ".member@example.invalid.idToken"], undefined, "and its token");
  assert.strictEqual(w.storage._data[PENDING], undefined, "the pending sign-out is applied, so the marker is cleared");
  assert.strictEqual(w.sandbox.hasStoredSessionKeys(), false, "no saved session is found, so the sign-in form is shown");
  await assert.rejects(w.sandbox.getValidSession(), /No saved session/, "the old session cannot be restored");
});

test("pre-marker tab: a Sign Out during the outage stays in force across repeated failed attempts and the recovery", async () => {
  let attempt = 0;
  const w = load({
    fetch: () => { attempt += 1; return Promise.resolve(attempt <= 2 ? jsonResponse(503, {}) : jsonResponse(200, GOOD)); },
    session: fakeSession("OLD-SESSION-TOKEN"),
    sessionItems: { ...PRE_MARKER },
  });
  await w.sandbox.signOutCurrentUser();
  await assert.rejects(w.sandbox.getValidSession(), (err) => err.code === "AuthUnavailable", "still unavailable: nothing is restored");
  assert.strictEqual(w.storage._data[LAST_USER], "member@example.invalid", "still unavailable: the keys wait for the configuration");
  await assert.rejects(w.sandbox.ensureAuthReady(), (err) => err.code === "AuthUnavailable", "a second failed attempt");
  assert.strictEqual(await w.sandbox.retryAuthConfig(), true);
  assert.strictEqual(w.storage._data[LAST_USER], undefined);
  await assert.rejects(w.sandbox.getValidSession(), /No saved session/);
});

test("pre-marker tab: after recovery the person can sign in again, and that new sign-in works", async () => {
  let attempt = 0;
  const w = load({
    fetch: () => { attempt += 1; return Promise.resolve(attempt === 1 ? jsonResponse(503, {}) : jsonResponse(200, GOOD)); },
    session: fakeSession("OLD-SESSION-TOKEN"),
    sessionItems: { ...PRE_MARKER },
  });
  await assert.rejects(w.sandbox.ensureAuthReady(), (err) => err.code === "AuthUnavailable");   // the outage
  await w.sandbox.signOutCurrentUser();
  await w.sandbox.retryAuthConfig();                                                             // recovery
  const result = await w.sandbox.signIn("member@example.invalid", "pw");
  assert.strictEqual(result.accessToken, "NEW-SIGN-IN-TOKEN", "a fresh sign-in is accepted");
  assert.strictEqual(w.storage._data[LAST_USER], "member@example.invalid", "the new sign-in is recorded");
});

test("remembered client, explicit sign-out during an outage: nothing comes back after recovery", async () => {
  let attempt = 0;
  const w = load({
    fetch: () => { attempt += 1; return Promise.resolve(attempt === 1 ? jsonResponse(503, {}) : jsonResponse(200, GOOD)); },
    session: fakeSession("OLD-SESSION-TOKEN"),
    sessionItems: { "ct.cognito-app-client": CLIENT, ...PRE_MARKER },
  });
  await assert.rejects(w.sandbox.ensureAuthReady(), (err) => err.code === "AuthUnavailable");   // the outage
  await w.sandbox.signOutCurrentUser();
  await w.sandbox.retryAuthConfig();                                                             // recovery
  assert.strictEqual(w.storage._data[LAST_USER], undefined);
  await assert.rejects(w.sandbox.getValidSession(), /No saved session/);
});

test("control: pre-marker tab, configuration loads normally: explicit sign-out removes this client's keys at once", async () => {
  const w = load({
    fetch: () => Promise.resolve(jsonResponse(200, GOOD)),
    session: fakeSession("OLD"),
    sessionItems: { ...PRE_MARKER },
  });
  await w.sandbox.ensureAuthReady();
  assert.strictEqual(w.storage._data["ct.cognito-app-client"], CLIENT, "the marker is written at load");
  await w.sandbox.signOutCurrentUser();
  assert.strictEqual(w.storage._data[LAST_USER], undefined);
  assert.strictEqual(w.storage._data[PENDING], undefined, "no pending sign-out was needed");
});
