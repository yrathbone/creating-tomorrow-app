// auth.js configuration from the server (no hard-coded fallback). Runs the real frontend/career/js/auth.js in a bare VM with a
// stub Cognito SDK and a stub fetch. Nothing is sent anywhere. Run:  node --test backend/tests/frontend
const test = require("node:test");
const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const FRONTEND = path.join(__dirname, "..", "..", "..", "frontend", "career");
const AUTH_SOURCE = fs.readFileSync(path.join(FRONTEND, "js", "auth.js"), "utf8");
const CLIENT = "testclient123456";
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

// The SDK's CognitoUser for the person who already has a saved session in this tab.
function fakeCurrentUser(session) {
  return {
    getSession(cb) { cb(null, session); },
    signOut(cb) { cb(); },
    refreshSession(rt, cb) { cb(null, fakeSession("REFRESHED-TOKEN")); },
    deleteUser(cb) { cb(null); },
  };
}

// A session the SDK would hand back: valid, with an access token.
function fakeSession(access = "ACCESS-TOKEN") {
  return {
    isValid: () => true,
    getAccessToken: () => ({ getJwtToken: () => access }),
    getIdToken: () => ({ getJwtToken: () => "ID-TOKEN" }),
    getRefreshToken: () => ({ getToken: () => "REFRESH" }),
  };
}

// opts.fetch: the function the sandbox's fetch will be. opts.currentUser: what the SDK's getCurrentUser returns (or null).
function loadAuth(opts = {}) {
  const pools = [];
  const users = [];
  const forgotCalls = [];
  class CognitoUserPool {
    constructor(o) { pools.push(o); this.o = o; }
    // Like the real SDK: there is a current user only while this tab still holds this client's sign-in marker.
    getCurrentUser() {
      const marker = storage.getItem("CognitoIdentityServiceProvider." + this.o.ClientId + ".LastAuthUser");
      return marker === null || opts.currentUser === undefined ? null : opts.currentUser;
    }
    signUp(email, pw, attrs, _x, cb) { cb(null, { user: email }); }
  }
  class CognitoUser {
    constructor(o) { this.o = o; users.push(this); }
    authenticateUser(details, cbs) { cbs.onSuccess(fakeSession("SIGNED-IN-TOKEN")); }
    getSession(cb) { cb(null, opts.currentUser ? opts.currentUser.session : null); }
    signOut(cb) { cb(); }
    refreshSession(rt, cb) { cb(null, fakeSession("REFRESHED-TOKEN")); }
    deleteUser(cb) { cb(null); }
    forgotPassword(cbs) { forgotCalls.push(this.o.Username); return cbs.inputVerificationCode ? cbs.inputVerificationCode() : cbs.onSuccess(); }
  }
  const storage = fakeStorage(opts.sessionItems || {});
  const local = fakeStorage(opts.localItems || {});
  const fetchCalls = [];
  const sandbox = {
    window: { sessionStorage: storage, localStorage: local },
    AmazonCognitoIdentity: {
      CognitoUserPool, CognitoUser,
      AuthenticationDetails: class { constructor(d) { this.d = d; } },
      CognitoUserAttribute: class { constructor(a) { this.a = a; } },
    },
    fetch: (url, init) => { fetchCalls.push({ url, init }); return opts.fetch(url, init); },
  };
  vm.createContext(sandbox);
  vm.runInContext(AUTH_SOURCE, sandbox);
  return { sandbox, pools, users, storage, local, fetchCalls, forgotCalls };
}

const okConfig = () => (url) => Promise.resolve(jsonResponse(200, GOOD));
const unavailable503 = () => () => Promise.resolve(jsonResponse(503, { detail: "Sign-in is not configured on this server." }));

// 1. Successful initialization
test("successful initialization builds the pool from the server's values and asks the right URL", async () => {
  const w = loadAuth({ fetch: okConfig() });
  assert.strictEqual(await w.sandbox.ensureAuthReady(), true);
  assert.strictEqual(w.fetchCalls.length, 1);
  assert.strictEqual(w.fetchCalls[0].url, "/api/career/auth-config");
  assert.strictEqual(w.fetchCalls[0].init.cache, "no-store");
  assert.strictEqual(w.pools.length, 1);
  assert.strictEqual(w.pools[0].UserPoolId, "us-east-2_TESTPOOL1");
  assert.strictEqual(w.pools[0].ClientId, CLIENT);
});

test("production-format values from the server are accepted (the same values production serves)", async () => {
  const body = { region: "us-east-2", user_pool_id: "us-east-2_uLhNvjpep", app_client_id: "5rfhr0o7799aa41a5odrt9i9hd" };
  const w = loadAuth({ fetch: () => Promise.resolve(jsonResponse(200, body)) });
  await w.sandbox.ensureAuthReady();
  assert.strictEqual(w.pools[0].UserPoolId, "us-east-2_uLhNvjpep");
});

test("no production Cognito value is written in auth.js any more", () => {
  assert.ok(!AUTH_SOURCE.includes("us-east-2_uLhNvjpep"), "the production pool id must not be hard-coded");
  assert.ok(!AUTH_SOURCE.includes("5rfhr0o7799aa41a5odrt9i9hd"), "the production client id must not be hard-coded");
});

// 2. Missing / invalid configuration
test("missing configuration (503) is refused: no pool is built and every action reports sign-in unavailable", async () => {
  const w = loadAuth({ fetch: unavailable503() });
  await assert.rejects(w.sandbox.ensureAuthReady(), (err) => {
    assert.strictEqual(err.code, "AuthUnavailable");
    assert.strictEqual(err.message, vm.runInContext("AUTH_UNAVAILABLE_MESSAGE", w.sandbox));
    return true;
  });
  await assert.rejects(w.sandbox.signIn("a@example.com", "pw"), (err) => err.code === "AuthUnavailable");
  assert.strictEqual(w.pools.length, 0, "no pool may be built without a configuration");
  assert.strictEqual(w.users.length, 0, "no sign-in may reach the SDK without a configuration");
});

test("invalid configuration is refused: wrong shape, mismatched region, malformed ids, and non-JSON answers", async () => {
  const bad = [
    { region: "us-east-2", user_pool_id: "us-east-2_TESTPOOL1" },                      // missing client id
    { region: "us-east-2", user_pool_id: "eu-west-1_TESTPOOL1", app_client_id: CLIENT }, // pool region differs from region
    { region: "us-east-2", user_pool_id: "us-east-2_TESTPOOL1", app_client_id: "short" },
    { region: "us-east-2", user_pool_id: "us-east-2_bad pool", app_client_id: CLIENT },
    { region: "US-EAST-2", user_pool_id: "us-east-2_TESTPOOL1", app_client_id: CLIENT },
    null,
    "not an object",
  ];
  for (const body of bad) {
    const w = loadAuth({ fetch: () => Promise.resolve(jsonResponse(200, body)) });
    await assert.rejects(w.sandbox.ensureAuthReady(), (err) => err.code === "AuthUnavailable", "accepted: " + JSON.stringify(body));
    assert.strictEqual(w.pools.length, 0, "a pool was built from: " + JSON.stringify(body));
  }
});

test("an answer that is not JSON at all is refused as unavailable", async () => {
  const w = loadAuth({ fetch: () => Promise.resolve({ ok: true, status: 200, json: async () => { throw new SyntaxError("bad json"); } }) });
  await assert.rejects(w.sandbox.ensureAuthReady(), (err) => err.code === "AuthUnavailable");
  assert.strictEqual(w.pools.length, 0);
});

// 3. Request failure, then recovery
test("a failed request is reported as unavailable, and the next attempt asks the server again and recovers", async () => {
  let attempt = 0;
  const w = loadAuth({ fetch: () => { attempt += 1; return attempt === 1 ? Promise.reject(new TypeError("network down")) : Promise.resolve(jsonResponse(200, GOOD)); } });
  await assert.rejects(w.sandbox.ensureAuthReady(), (err) => err.code === "AuthUnavailable");
  assert.strictEqual(w.pools.length, 0);
  assert.strictEqual(await w.sandbox.retryAuthConfig(), true);
  assert.strictEqual(w.fetchCalls.length, 2, "the failure is not cached: the retry asked the server again");
  assert.strictEqual(w.pools.length, 1);
});

test("concurrent actions share one configuration request", async () => {
  const w = loadAuth({ fetch: okConfig() });
  await Promise.all([w.sandbox.ensureAuthReady(), w.sandbox.ensureAuthReady(), w.sandbox.ensureAuthReady()]);
  assert.strictEqual(w.fetchCalls.length, 1);
});

// 4. Every action waits for the configuration
test("an action started before the configuration loads waits for it, then runs", async () => {
  let release;
  const gate = new Promise((resolve) => { release = resolve; });
  const w = loadAuth({ fetch: () => gate.then(() => jsonResponse(200, GOOD)) });
  const pending = w.sandbox.signIn("a@example.com", "pw");
  await new Promise((r) => setTimeout(r, 0));
  assert.strictEqual(w.pools.length, 0, "nothing is built while the configuration is still loading");
  assert.strictEqual(w.users.length, 0, "the SDK is not called while the configuration is still loading");
  release();
  const result = await pending;
  assert.strictEqual(result.accessToken, "SIGNED-IN-TOKEN");
  assert.strictEqual(w.pools[0].UserPoolId, "us-east-2_TESTPOOL1");
});

test("sign-up waits for the configuration, then builds the pool and succeeds", async () => {
  const w = loadAuth({ fetch: okConfig() });
  const result = await w.sandbox.signUp("new@example.com", "pw");
  assert.deepStrictEqual(result, { user: "new@example.com" });
  assert.strictEqual(w.pools.length, 1, "sign-up built the pool from the loaded configuration");
  assert.strictEqual(w.fetchCalls.length, 1);
});

test("requestPasswordReset waits for the configuration, then asks Cognito for the code", async () => {
  let release;
  const gate = new Promise((resolve) => { release = resolve; });
  const w = loadAuth({ fetch: () => gate.then(() => jsonResponse(200, GOOD)) });
  const pending = w.sandbox.requestPasswordReset("member@example.invalid");
  await new Promise((r) => setTimeout(r, 0));
  assert.strictEqual(w.forgotCalls.length, 0, "no reset is requested while the configuration is still loading");
  assert.strictEqual(w.pools.length, 0, "no pool is built while the configuration is still loading");
  release();
  await pending;  // resolves once Cognito reports that the code was sent
  assert.deepStrictEqual(w.forgotCalls, ["member@example.invalid"], "the reset was requested for the address given");
  assert.strictEqual(w.pools[0].UserPoolId, "us-east-2_TESTPOOL1", "the pool used is the configured one");
});

test("requestPasswordReset during a configuration outage rejects as unavailable and requests nothing", async () => {
  const w = loadAuth({ fetch: unavailable503() });
  await assert.rejects(w.sandbox.requestPasswordReset("member@example.invalid"), (err) => err.code === "AuthUnavailable");
  assert.deepStrictEqual(w.forgotCalls, [], "no reset code is requested without a configuration");
});

// 5. Existing session handling
test("an existing session is restored once the configuration has loaded", async () => {
  const session = fakeSession("RESTORED-TOKEN");
  const w = loadAuth({
    fetch: okConfig(),
    currentUser: fakeCurrentUser(session),
    sessionItems: { ["CognitoIdentityServiceProvider." + CLIENT + ".LastAuthUser"]: "member@example.invalid" },
  });
  assert.strictEqual(w.sandbox.hasStoredSessionKeys(), false, "before the configuration loads, the local check says no (it needs the client id)");
  await w.sandbox.ensureAuthReady();
  assert.strictEqual(w.sandbox.hasStoredSessionKeys(), true, "after loading, the same stored key is found");
  const restored = await w.sandbox.getValidSession();
  assert.strictEqual(restored.getAccessToken().getJwtToken(), "RESTORED-TOKEN");
});

test("an existing session is NOT signed out when the configuration cannot load", async () => {
  const key = "CognitoIdentityServiceProvider." + CLIENT + ".LastAuthUser";
  const w = loadAuth({ fetch: unavailable503(), currentUser: fakeCurrentUser(fakeSession()), sessionItems: { [key]: "member@example.invalid", [`CognitoIdentityServiceProvider.${CLIENT}.idToken`]: "x" } });
  await assert.rejects(w.sandbox.getValidSession(), (err) => err.code === "AuthUnavailable");
  w.sandbox.clearCognitoSessionKeys();    // the automatic path never clears: the prefix is unknown until the configuration loads
  assert.ok(w.storage._data[key], "the stored sign-in marker must survive a failed configuration load");
  assert.ok(w.storage._data[`CognitoIdentityServiceProvider.${CLIENT}.idToken`], "the stored token must survive too");
});

test("sign-out after the configuration loads clears this client's SDK keys and leaves other keys", async () => {
  const key = "CognitoIdentityServiceProvider." + CLIENT + ".LastAuthUser";
  const w = loadAuth({ fetch: okConfig(), currentUser: fakeCurrentUser(fakeSession()), sessionItems: { [key]: "m", other: "keep" } });
  await w.sandbox.ensureAuthReady();
  await w.sandbox.signOutCurrentUser();
  assert.strictEqual(w.storage._data[key], undefined);
  assert.strictEqual(w.storage._data.other, "keep");
});

// 6. Explicit sign-out during a configuration outage
test("explicit sign-out during an outage clears the SDK keys at once, without waiting for the network, and keeps unrelated storage", async () => {
  const sdk = "CognitoIdentityServiceProvider.";
  const w = loadAuth({
    fetch: () => new Promise(() => {}),   // the configuration request never answers
    currentUser: fakeCurrentUser(fakeSession()),
    sessionItems: {
      [sdk + CLIENT + ".LastAuthUser"]: "member@example.invalid",
      [sdk + CLIENT + ".idToken"]: "id",
      [sdk + "otherclient0000000.LastAuthUser"]: "someone-else",
      "ct.auth-notice": "Your session has ended.",
      "ct.unrelated": "keep",
    },
    localItems: { [sdk + CLIENT + ".LastAuthUser"]: "old", unrelated: "keep" },
  });
  const done = w.sandbox.signOutCurrentUser();          // not awaited: the keys must already be gone
  assert.strictEqual(w.storage._data[sdk + CLIENT + ".LastAuthUser"], undefined, "this client's marker is removed now");
  assert.strictEqual(w.storage._data[sdk + CLIENT + ".idToken"], undefined, "this client's tokens are removed now");
  assert.strictEqual(w.storage._data[sdk + "otherclient0000000.LastAuthUser"], undefined, "any other SDK key in this tab is removed too");
  assert.strictEqual(w.storage._data["ct.auth-notice"], "Your session has ended.", "the sign-in notice stays");
  assert.strictEqual(w.storage._data["ct.unrelated"], "keep", "unrelated session storage stays");
  assert.strictEqual(w.local._data[sdk + CLIENT + ".LastAuthUser"], undefined, "a leftover local copy is removed");
  assert.strictEqual(w.local._data.unrelated, "keep", "unrelated local storage stays");
  await done;                                           // resolves without the network
  assert.strictEqual(w.pools.length, 0, "no pool was built without a configuration");
});

test("explicit sign-out during an outage stays in force after the configuration recovers: the old session is not restored", async () => {
  const key = "CognitoIdentityServiceProvider." + CLIENT + ".LastAuthUser";
  let attempt = 0;
  const w = loadAuth({
    fetch: () => { attempt += 1; return attempt === 1 ? Promise.resolve(jsonResponse(503, {})) : Promise.resolve(jsonResponse(200, GOOD)); },
    currentUser: fakeCurrentUser(fakeSession("OLD-SESSION-TOKEN")),
    sessionItems: { [key]: "member@example.invalid", [`CognitoIdentityServiceProvider.${CLIENT}.idToken`]: "id" },
  });
  await assert.rejects(w.sandbox.ensureAuthReady(), (err) => err.code === "AuthUnavailable");   // the outage
  await w.sandbox.signOutCurrentUser();                                                            // explicit sign-out during the outage
  assert.strictEqual(await w.sandbox.retryAuthConfig(), true, "the configuration recovers");     // recovery
  assert.strictEqual(w.sandbox.hasStoredSessionKeys(), false, "the saved sign-in marker is gone, so nothing is restored");
  await assert.rejects(w.sandbox.getValidSession(), /No saved session/, "the old session cannot be restored after recovery");
  assert.strictEqual(w.storage._data[key], undefined);
  assert.strictEqual(w.storage._data[`CognitoIdentityServiceProvider.${CLIENT}.idToken`], undefined);
});

test("automatic configuration failures remain non-destructive: a failed restore keeps the saved session for a later retry", async () => {
  const key = "CognitoIdentityServiceProvider." + CLIENT + ".LastAuthUser";
  let attempt = 0;
  const w = loadAuth({
    fetch: () => { attempt += 1; return attempt === 1 ? Promise.resolve(jsonResponse(503, {})) : Promise.resolve(jsonResponse(200, GOOD)); },
    currentUser: fakeCurrentUser(fakeSession("STILL-VALID")),
    sessionItems: { [key]: "member@example.invalid" },
  });
  await assert.rejects(w.sandbox.getValidSession(), (err) => err.code === "AuthUnavailable");   // automatic restore, outage
  assert.strictEqual(w.storage._data[key], "member@example.invalid", "the saved session is not removed by a failed automatic restore");
  await w.sandbox.retryAuthConfig();                                                             // recovery
  const restored = await w.sandbox.getValidSession();
  assert.strictEqual(restored.getAccessToken().getJwtToken(), "STILL-VALID", "the same session is restored after recovery");
});

test("a leftover localStorage session for this client is removed; other localStorage keys are kept", async () => {
  const legacy = "CognitoIdentityServiceProvider." + CLIENT + ".LastAuthUser";
  const w = loadAuth({ fetch: okConfig(), localItems: { [legacy]: "old", unrelated: "keep" } });
  await w.sandbox.ensureAuthReady();
  assert.strictEqual(w.local._data[legacy], undefined);
  assert.strictEqual(w.local._data.unrelated, "keep");
});

test("the local page-start hint needs no configuration and only looks for a sign-in marker", () => {
  const w = loadAuth({ fetch: () => { throw new Error("must not be called"); }, sessionItems: { "CognitoIdentityServiceProvider.anything.LastAuthUser": "m" } });
  assert.strictEqual(w.sandbox.looksLikeStoredSession(), true);
  assert.strictEqual(w.fetchCalls.length, 0);
});

test("isAuthUnavailable recognises only the unavailable error", () => {
  const w = loadAuth({ fetch: okConfig() });
  assert.strictEqual(w.sandbox.isAuthUnavailable(w.sandbox.authUnavailableError()), true);
  assert.strictEqual(w.sandbox.isAuthUnavailable(new Error("other")), false);
  assert.strictEqual(w.sandbox.isAuthUnavailable(null), false);
});
