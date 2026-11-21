// Retention policy for the browser (frontend only; the server-side rules are not covered here).
//  1. Guest work (the public tools, before any sign-in) is not persisted in the browser. Nothing is written to local or session
//     storage by those pages.
//  2. Sign-out removes guest work held in the browser (keys under "ct.guest.") and nothing else in storage.
//  3. Signed-in resumes are saved on the server and listed in the "Resumes Built" panel. Sign-out does not delete them, and the
//     guest cleanup never touches them. The signed-in panel reads the server list, not the browser.
const test = require("node:test");
const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const FRONTEND = path.join(__dirname, "..", "..", "..", "frontend");
const CAREER = path.join(FRONTEND, "career");
const read = (...p) => fs.readFileSync(path.join(FRONTEND, ...p), "utf8");

// Literal keys the signed-in dashboard and the sign-in flow are allowed to write to browser storage.
const ALLOWED_WRITE_KEYS = new Set([
  "ct_application_view",   // the applications view preference
  "ct_skill_view",         // the skills view preference
  "ct.storage-probe",      // auth.js: checks that session storage works (removed at once)
  "ct.auth-notice",        // login.js: one-time sign-in notice
  "ct.cognito-app-client", // auth.js and auth-nav.js: the app client this tab last loaded (an identifier, not a secret)
  "ct.signed-out-pending", // auth.js: an explicit sign-out made while the configuration was unavailable
]);
// Writes whose key is a variable. Only the SDK-facing helpers in auth.js may do this, and each name is listed here.
const ALLOWED_DYNAMIC_WRITERS = new Set(["probe", "key", "APP_CLIENT_STORE_KEY", "SIGNED_OUT_PENDING_KEY", "AUTH_NOTICE_KEY", "k"]);

// Every setItem( call on a storage object: window.localStorage / window.sessionStorage (or the bare names), the SDK store
// helper signInStore(), and the local aliases "s" and "store" used in auth.js.
function storageWrites(source) {
  const out = [];
  const re = /(?:\b(?:window\.)?(?:localStorage|sessionStorage)|\bsignInStore\(\)|\bs|\bstore)\.setItem\(\s*([^,)]+)/g;
  let m;
  while ((m = re.exec(source)) !== null) out.push(m[1].trim());
  return out;
}

test("guest pages write nothing to browser storage (guest work is not persisted)", () => {
  const guestFiles = fs.readdirSync(FRONTEND)
    .filter((f) => /\.(js|html)$/.test(f) && f !== "auth-nav.js");
  assert.ok(guestFiles.length > 5, "the guest pages were found");
  for (const f of guestFiles) {
    const src = fs.readFileSync(path.join(FRONTEND, f), "utf8");
    assert.deepStrictEqual(storageWrites(src), [], `${f} must not write browser storage`);
  }
});

test("every browser-storage write in the signed-in dashboard uses a known key", () => {
  const files = fs.readdirSync(path.join(CAREER, "js")).filter((f) => f.endsWith(".js")).concat(["../login.js"]);
  for (const f of files) {
    const src = fs.readFileSync(path.join(CAREER, "js", f), "utf8");
    for (const arg of storageWrites(src)) {
      const literal = /^"([^"]+)"$/.exec(arg);
      if (literal) {
        assert.ok(ALLOWED_WRITE_KEYS.has(literal[1]), `${f} writes an unlisted key: ${literal[1]}`);
      } else {
        const name = arg.replace(/\s.*$/, "");
        assert.ok(ALLOWED_DYNAMIC_WRITERS.has(name), `${f} writes a key from a variable (${arg}); review it`);
      }
    }
  }
});

// --- sign-out behaviour, run on the real auth.js ---
const CLIENT = "testclient123456";
const SDK = "CognitoIdentityServiceProvider.";
const GOOD = { region: "us-east-2", user_pool_id: "us-east-2_TESTPOOL1", app_client_id: CLIENT };
const AUTH_SOURCE = read("career", "js", "auth.js");

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
function load({ fetch, sessionItems = {}, localItems = {} }) {
  const storage = fakeStorage(sessionItems);
  const local = fakeStorage(localItems);
  const calls = [];
  class CognitoUserPool { getCurrentUser() { return null; } }
  const sandbox = {
    window: { sessionStorage: storage, localStorage: local },
    AmazonCognitoIdentity: { CognitoUserPool, CognitoUser: class {}, AuthenticationDetails: class {}, CognitoUserAttribute: class {} },
    fetch: (url, init) => { calls.push({ url, method: (init && init.method) || "GET" }); return fetch(url); },
  };
  vm.createContext(sandbox);
  vm.runInContext(AUTH_SOURCE, sandbox);
  return { sandbox, storage, local, calls };
}

const TAB_STATE = {
  "ct_application_view": "list",
  "ct_skill_view": "grid",
  "ct.auth-notice": "Your session has ended.",
  "ct.guest.draft": "guest resume text",
  "ct.guest.scan": "guest job text",
  "unrelated": "keep",
};
const LOCAL_STATE = { "ct.guest.draft": "guest copy in local", "unrelated": "keep" };

for (const [label, fetch] of [
  ["configuration outage", () => Promise.resolve(jsonResponse(503, {}))],
  ["configuration loads", () => Promise.resolve(jsonResponse(200, GOOD))],
]) {
  test(`sign-out during a ${label} removes guest work, keeps the signed-in list and other keys, and calls no server route`, async () => {
    const w = load({ fetch, sessionItems: { ...TAB_STATE }, localItems: { ...LOCAL_STATE } });
    await w.sandbox.signOutCurrentUser();
    assert.strictEqual(w.storage._data["ct.guest.draft"], undefined, "guest draft removed (session)");
    assert.strictEqual(w.storage._data["ct.guest.scan"], undefined, "guest scan removed (session)");
    assert.strictEqual(w.local._data["ct.guest.draft"], undefined, "guest draft removed (local)");
    assert.strictEqual(w.storage._data["ct_application_view"], "list", "view preference is not guest work and is kept");
    assert.strictEqual(w.storage._data["ct_skill_view"], "grid", "view preference is kept");
    assert.strictEqual(w.storage._data["unrelated"], "keep", "unrelated key kept");
    assert.strictEqual(w.local._data.unrelated, "keep", "unrelated local key kept");
    assert.deepStrictEqual(w.calls, [], "sign-out makes no server request: the signed-in resume list is not touched");
  });
}

test("guest cleanup does not remove signed-in resume data: no delete request is made by any sign-out path", async () => {
  const w = load({ fetch: () => Promise.resolve(jsonResponse(503, {})), sessionItems: { "ct.guest.draft": "x" } });
  await w.sandbox.signOutCurrentUser();
  assert.ok(!w.calls.some((c) => c.method !== "GET"), "no write or delete request");
});

// --- the signed-in "Resumes Built" panel ---
test("the signed-in resume history is the Resumes Built panel, read from the server list", () => {
  const html = read("career", "login.html");
  assert.match(html, /id="panel-resumes-heading"[^>]*>Resumes Built</, "the panel is titled Resumes Built");
  const history = read("career", "js", "history.js");
  assert.match(history, /fetch|authedFetch\("\/api\/career\/resume-versions"\)/, "history.js reads the server list of resume versions");
  assert.ok(!/localStorage|sessionStorage/.test(history), "history.js keeps no browser copy of the resumes");
});

function jsonResponse(status, body) {
  return { ok: status >= 200 && status < 300, status, json: async () => body };
}
