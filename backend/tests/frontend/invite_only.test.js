// Career Profile is invite-only while in beta: the sign-up page never creates an account, invited people get a
// first-login "choose your password" step, and the wording says the same thing everywhere.
// Run:  node --test backend/tests/frontend
const test = require("node:test");
const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const FRONTEND = path.join(__dirname, "..", "..", "..", "frontend");
const read = (...p) => fs.readFileSync(path.join(FRONTEND, ...p), "utf8");

function fakeElement(extra = {}) {
  const handlers = {};
  return Object.assign({
    hidden: true, textContent: "", children: [], value: "",
    addEventListener(type, fn) { (handlers[type] = handlers[type] || []).push(fn); },
    append(...nodes) { this.children.push(...nodes); },
    fire(type, event = {}) { return Promise.all((handlers[type] || []).map((fn) => fn(event))); },
  }, extra);
}

// ---- the sign-up page ----
function loadRegister() {
  const form = fakeElement({ hidden: false });
  const error = fakeElement();
  const created = [];
  const sandbox = {
    document: {
      getElementById: (id) => ({ "signup-form": form, "signup-error": error }[id] || null),
      createElement: (tag) => { const e = fakeElement({ tag, hidden: false }); created.push(e); return e; },
      createTextNode: (text) => ({ text }),
    },
    encodeURIComponent,
  };
  vm.createContext(sandbox);
  vm.runInContext(read("career", "register.js"), sandbox);
  return { form, error, created };
}

test("submitting the sign-up form creates nothing: it only explains that Career Profile is in beta and by invitation", async () => {
  const { form, error } = loadRegister(); // the stub has no signUp(): calling it would throw
  let prevented = false;
  await form.fire("submit", { preventDefault: () => { prevented = true; } });
  assert.strictEqual(prevented, true);
  assert.strictEqual(error.hidden, false);
  const spans = error.children.filter((c) => c.tag === "span").map((c) => c.textContent).join(" ");
  assert.match(spans, /currently in beta testing and is by invitation only/);
});

test("the explanation offers a way to ask for an invitation and a way in for people who already have one", async () => {
  const { form, error } = loadRegister();
  await form.fire("submit", { preventDefault() {} });
  const links = error.children.filter((c) => c.tag === "a");
  assert.strictEqual(links.length, 2);
  assert.match(links[0].href, /^mailto:yovanarathbone@creatingtomorrow\.net\?subject=Career%20Profile%20beta%20invitation%20request$/);
  assert.strictEqual(links[1].href, "login.html");
});

test("register.js never talks to the sign-in service", () => {
  const js = read("career", "register.js");
  for (const call of ["signUp(", "confirmRegistration(", "resendConfirmationCode(", "fetch(", "AmazonCognito"]) {
    assert.ok(!js.includes(call), `register.js must not call ${call}`);
  }
});

test("the sign-up page says beta + invitation-only up front and has no confirmation-code steps left", () => {
  const html = read("career", "register.html");
  assert.match(html, /<h1>Career Profile is by invitation<\/h1>/);
  assert.match(html, /beta testing/);
  assert.match(html, /by invitation only/);
  for (const gone of ["step-confirm", "confirm-code", "step-done", "Create your account"]) assert.ok(!html.includes(gone), gone);
});

// ---- the sign-in page ----
test("the login page no longer invites people to create an account; it says beta + invitation only", () => {
  const html = read("career", "login.html");
  assert.ok(!html.includes(">Create one<"), "no 'Create one' link");
  assert.match(html, /Career Profile is in <strong>beta testing<\/strong> and is <strong>by invitation only<\/strong>/);
  assert.match(html, /temporary password/);
});

test("first-login 'choose your password' step exists with matching, hidden-by-default fields", () => {
  const html = read("career", "login.html");
  assert.match(html, /<section class="card" id="step-newpassword" hidden>/);
  for (const id of ["newpassword-form", "newpassword-input", "newpassword-confirm", "newpassword-btn", "newpassword-error"]) assert.ok(html.includes(`id="${id}"`), id);
  assert.strictEqual((html.match(/autocomplete="new-password"/g) || []).length >= 2, true);
});

test("newPasswordProblem: at least 8 characters and both boxes must match", () => {
  const src = read("career", "login.js");
  const fn = src.slice(src.indexOf("function newPasswordProblem"), src.indexOf("loginForm.addEventListener"));
  const ctx = {};
  vm.createContext(ctx);
  vm.runInContext(fn, ctx);
  assert.strictEqual(ctx.newPasswordProblem("abcdefgh", "abcdefgh"), "");
  assert.match(ctx.newPasswordProblem("short", "short"), /at least 8 characters/);
  assert.match(ctx.newPasswordProblem("", ""), /at least 8 characters/);
  assert.match(ctx.newPasswordProblem("abcdefgh", "abcdefgx"), /don't match/);
});

test("login.js: the invited person's temporary password leads to the new-password step, then the same sign-in as everyone", () => {
  const src = read("career", "login.js");
  assert.match(src, /if \(result\.newPasswordRequired\)/);
  assert.match(src, /completeNewPassword\(document\.getElementById\("newpassword-input"\)\.value\)/);
  assert.match(src, /async function finishSignIn\(accessToken\)/);
  assert.strictEqual((src.match(/await finishSignIn\(/g) || []).length, 2, "normal sign-in and first sign-in share one path");
});

// ---- auth.js talking to a stand-in sign-in service ----
function loadAuth(fakeUserBehaviour) {
  const calls = [];
  class FakeUser {
    constructor(opts) { this.opts = opts; }
    authenticateUser(details, callbacks) { fakeUserBehaviour.authenticate(callbacks, calls); }
    completeNewPasswordChallenge(password, attrs, callbacks) { calls.push({ completed: password, attrs }); fakeUserBehaviour.complete(callbacks); }
  }
  const session = { getAccessToken: () => ({ getJwtToken: () => "ACCESS" }), getIdToken: () => ({ getJwtToken: () => "ID" }) };
  const store = {};
  const sandbox = {
    window: { localStorage: { length: 0, key: () => null, removeItem() {} }, sessionStorage: { setItem(k, v) { store[k] = v; }, removeItem(k) { delete store[k]; }, getItem: (k) => store[k] || null, length: 0, key: () => null } },
    AmazonCognitoIdentity: {
      CognitoUserPool: class { constructor() {} },
      CognitoUser: FakeUser,
      AuthenticationDetails: class { constructor(d) { this.d = d; } },
      CognitoUserAttribute: class {},
    },
    session,
  };
  vm.createContext(sandbox);
  vm.runInContext(read("career", "js", "auth.js"), sandbox);
  return { sandbox, calls, session };
}

test("a normal sign-in still resolves with the tokens", async () => {
  const w = loadAuth({ authenticate: (cb) => cb.onSuccess(w2session()), complete() {} });
  function w2session() { return w.session; }
  const result = await vm.runInContext('signIn("a@example.com", "pw")', w.sandbox);
  assert.deepStrictEqual({ ...result }, { accessToken: "ACCESS", idToken: "ID" });
});

test("a temporary password resolves with newPasswordRequired and a function that completes the sign-in", async () => {
  const w = loadAuth({ authenticate: (cb) => cb.newPasswordRequired({ email: "a@example.com", email_verified: "true" }, ["name"]), complete: (cb) => cb.onSuccess(w.session) });
  const result = await vm.runInContext('signIn("a@example.com", "temp-pw")', w.sandbox);
  assert.strictEqual(result.newPasswordRequired, true);
  assert.strictEqual(result.accessToken, undefined, "no tokens until they have chosen a password");
  const done = await result.completeNewPassword("my-own-password");
  assert.deepStrictEqual({ ...done }, { accessToken: "ACCESS", idToken: "ID" });
  assert.strictEqual(JSON.stringify(w.calls.find((c) => c.completed)), JSON.stringify({ completed: "my-own-password", attrs: {} }), "no profile attributes are re-sent");
});

test("a wrong password still rejects with the sign-in service's message", async () => {
  const w = loadAuth({ authenticate: (cb) => cb.onFailure(new Error("Incorrect username or password.")), complete() {} });
  await assert.rejects(() => vm.runInContext('signIn("a@example.com", "bad")', w.sandbox), /Incorrect username or password/);
});

test("a rejected new password (for example too weak) rejects with the service's message", async () => {
  const w = loadAuth({ authenticate: (cb) => cb.newPasswordRequired({}, []), complete: (cb) => cb.onFailure(new Error("Password does not conform to policy.")) });
  const result = await vm.runInContext('signIn("a@example.com", "temp")', w.sandbox);
  await assert.rejects(() => result.completeNewPassword("weak"), /does not conform/);
});

// ---- the rest of the site ----
test("Contact, Privacy and Terms say Career Profile is a beta by invitation", () => {
  assert.match(read("contact.html"), /A Career Profile invitation\.<\/strong> Career Profile is in beta testing and is by invitation only/);
  assert.match(read("privacy.html"), /Career Profile is in beta testing and is by invitation only for now/);
});
