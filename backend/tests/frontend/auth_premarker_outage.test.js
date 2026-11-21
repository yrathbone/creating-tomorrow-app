// Pre-marker existing session: a tab whose SDK sign-in keys were written BEFORE the remembered-client marker
// ("ct.cognito-app-client") existed, so the tab has no remembered client. These tests record the CURRENT behaviour in that
// case. Where the behaviour is a known gap, the test name says so and asserts the gap, so that any change is noticed.
// Runs the real frontend/career/js/auth.js in a bare VM with a stub SDK and a stub fetch. Nothing is sent anywhere.
const test = require("node:test");
const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const FRONTEND = path.join(__dirname, "..", "..", "..", "frontend", "career");
const AUTH_SOURCE = fs.readFileSync(path.join(FRONTEND, "js", "auth.js"), "utf8");
const CLIENT = "testclient123456";
const SDK = "CognitoIdentityServiceProvider.";
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
function fakeCurrentUser(session) {
  return {
    getSession(cb) { cb(null, session); },
    signOut(cb) { cb(); },
    refreshSession(rt, cb) { cb(null, session); },
    deleteUser(cb) { cb(null); },
  };
}
function load({ fetch, session, sessionItems, localItems = {} }) {
  class CognitoUserPool { constructor() {} getCurrentUser() { return session ? fakeCurrentUser(session) : null; } }
  const storage = fakeStorage(sessionItems);
  const local = fakeStorage(localItems);
  const sandbox = {
    window: { sessionStorage: storage, localStorage: local },
    AmazonCognitoIdentity: {
      CognitoUserPool, CognitoUser: class {},
      AuthenticationDetails: class {}, CognitoUserAttribute: class {},
    },
    fetch,
  };
  vm.createContext(sandbox);
  vm.runInContext(AUTH_SOURCE, sandbox);
  return { sandbox, storage, local };
}

const PRE_MARKER_KEYS = {
  [SDK + CLIENT + ".LastAuthUser"]: "member@example.invalid",
  [SDK + CLIENT + ".member@example.invalid.idToken"]: "id",
};
const outage = () => () => Promise.resolve(jsonResponse(503, {}));

test("pre-marker tab: the tab has SDK keys and no remembered client, so the marker is absent", () => {
  const w = load({ fetch: outage(), sessionItems: { ...PRE_MARKER_KEYS } });
  assert.strictEqual(w.storage._data["ct.cognito-app-client"], undefined);
  assert.strictEqual(w.sandbox.hasStoredSessionKeys(), false, "before the configuration loads the local check cannot find the key");
});

test("KNOWN GAP: pre-marker tab, explicit sign-out during an outage removes nothing (current behaviour, recorded)", async () => {
  const w = load({ fetch: outage(), session: fakeSession("OLD"), sessionItems: { ...PRE_MARKER_KEYS } });
  await w.sandbox.signOutCurrentUser();
  assert.strictEqual(w.storage._data[SDK + CLIENT + ".LastAuthUser"], "member@example.invalid",
    "KNOWN GAP: the saved sign-in marker survives an explicit sign-out during an outage in a pre-marker tab");
  assert.strictEqual(w.storage._data[SDK + CLIENT + ".member@example.invalid.idToken"], "id",
    "KNOWN GAP: the saved token survives too");
});

test("KNOWN GAP: pre-marker tab, the old session is restored after the configuration recovers (current behaviour, recorded)", async () => {
  let attempt = 0;
  const w = load({
    fetch: () => { attempt += 1; return Promise.resolve(attempt === 1 ? jsonResponse(503, {}) : jsonResponse(200, GOOD)); },
    session: fakeSession("OLD-SESSION-TOKEN"),
    sessionItems: { ...PRE_MARKER_KEYS },
  });
  await assert.rejects(w.sandbox.ensureAuthReady(), (err) => err.code === "AuthUnavailable");   // the outage, as the page sees it
  await w.sandbox.signOutCurrentUser();                                                          // the person clicks Sign Out
  assert.strictEqual(await w.sandbox.retryAuthConfig(), true, "the configuration recovers (the page's Try again)");
  assert.strictEqual(w.sandbox.hasStoredSessionKeys(), true, "KNOWN GAP: the sign-in marker is found after recovery");
  const restored = await w.sandbox.getValidSession();
  assert.strictEqual(restored.getAccessToken().getJwtToken(), "OLD-SESSION-TOKEN",
    "KNOWN GAP: the explicitly signed-out session is restored after recovery, so the person is signed back in without signing in");
});

test("control: pre-marker tab, configuration loads normally: explicit sign-out removes this client's keys", async () => {
  const w = load({
    fetch: () => Promise.resolve(jsonResponse(200, GOOD)),
    session: fakeSession("OLD"),
    sessionItems: { ...PRE_MARKER_KEYS },
  });
  await w.sandbox.ensureAuthReady();
  assert.strictEqual(w.storage._data["ct.cognito-app-client"], CLIENT, "the marker is written at load");
  await w.sandbox.signOutCurrentUser();
  assert.strictEqual(w.storage._data[SDK + CLIENT + ".LastAuthUser"], undefined);
  assert.strictEqual(w.storage._data[SDK + CLIENT + ".member@example.invalid.idToken"], undefined);
});
