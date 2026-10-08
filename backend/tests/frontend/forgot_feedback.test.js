// "Forgot password" (Cognito emails a code; the browser sends it back with the new password) and the beta feedback card.
// Run:  node --test backend/tests/frontend
const test = require("node:test");
const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const FRONTEND = path.join(__dirname, "..", "..", "..", "frontend");
const read = (...p) => fs.readFileSync(path.join(FRONTEND, ...p), "utf8");
const loginHtml = read("career", "login.html");
const loginJs = read("career", "login.js");

// ---- the page ----
test("the login page offers 'Forgot your password?' and a way to email for help", () => {
  assert.match(loginHtml, /id="forgot-open-btn"[^>]*>Forgot your password\?<\/button>/);
  assert.match(loginHtml, /href="mailto:yovanarathbone@creatingtomorrow\.net\?subject=Career%20Profile%20sign-in%20help"/);
});

test("the reset card is hidden until asked for and has the code, new-password and again boxes", () => {
  assert.match(loginHtml, /<section class="card" id="step-forgot" hidden>/);
  for (const id of ["forgot-request-form", "forgot-email", "forgot-confirm-form", "forgot-code", "forgot-new-password", "forgot-new-password-confirm", "forgot-confirm-btn", "forgot-resend-btn", "forgot-back-btn", "forgot-error", "login-notice"]) {
    assert.ok(loginHtml.includes(`id="${id}"`), id);
  }
  assert.match(loginHtml, /<form id="forgot-confirm-form" hidden>/, "the code step stays hidden until a code was requested");
  assert.match(loginHtml, /autocomplete="one-time-code"/);
  assert.match(loginHtml, /<p id="forgot-sent-message" role="status">If that email has a Career Profile account/, "wording never says whether the account exists");
});

// ---- auth.js talking to a stand-in sign-in service ----
function loadAuth(behaviour) {
  const calls = [];
  class FakeUser {
    constructor(opts) { calls.push({ user: opts.Username }); }
    forgotPassword(cbs) { behaviour.forgot(cbs); }
    confirmPassword(code, pw, cbs) { calls.push({ code, pw }); behaviour.confirm(cbs); }
  }
  const sandbox = {
    window: { localStorage: { length: 0, key: () => null, removeItem() {} }, sessionStorage: { setItem() {}, removeItem() {}, getItem: () => null, length: 0, key: () => null } },
    AmazonCognitoIdentity: { CognitoUserPool: class {}, CognitoUser: FakeUser, AuthenticationDetails: class {}, CognitoUserAttribute: class {} },
  };
  vm.createContext(sandbox);
  vm.runInContext(read("career", "js", "auth.js"), sandbox);
  return { sandbox, calls };
}

test("requestPasswordReset resolves as soon as the code has been sent", async () => {
  const w = loadAuth({ forgot: (cb) => cb.inputVerificationCode({}), confirm() {} });
  await vm.runInContext('requestPasswordReset("a@example.com")', w.sandbox);
  assert.strictEqual(w.calls[0].user, "a@example.com");
});

test("requestPasswordReset passes the service's error through", async () => {
  const err = Object.assign(new Error("Too many"), { code: "LimitExceededException" });
  const w = loadAuth({ forgot: (cb) => cb.onFailure(err), confirm() {} });
  await assert.rejects(() => vm.runInContext('requestPasswordReset("a@example.com")', w.sandbox), (e) => e.code === "LimitExceededException");
});

test("confirmPasswordReset sends the code and the new password, nothing else", async () => {
  const w = loadAuth({ forgot() {}, confirm: (cb) => cb.onSuccess("SUCCESS") });
  await vm.runInContext('confirmPasswordReset("a@example.com", "123456", "my-new-password")', w.sandbox);
  assert.deepStrictEqual({ ...w.calls.find((c) => c.code) }, { code: "123456", pw: "my-new-password" });
});

test("a wrong code rejects with the service's error code", async () => {
  const err = Object.assign(new Error("Invalid code"), { code: "CodeMismatchException" });
  const w = loadAuth({ forgot() {}, confirm: (cb) => cb.onFailure(err) });
  await assert.rejects(() => vm.runInContext('confirmPasswordReset("a@example.com", "000000", "pw-long-enough")', w.sandbox), (e) => e.code === "CodeMismatchException");
});

// ---- login.js pieces that can be run on their own ----
function runSlice(from, to, extra = {}) {
  const src = loginJs.slice(loginJs.indexOf(from), loginJs.indexOf(to));
  const ctx = { ...extra };
  vm.createContext(ctx);
  vm.runInContext(src, ctx);
  return ctx;
}

test("passwordResetMessage: plain words for each failure, and the service's own text when it has one", () => {
  const ctx = runSlice("function passwordResetMessage", "loginForm.addEventListener");
  const m = (code, message) => ctx.passwordResetMessage({ code, message });
  assert.match(m("CodeMismatchException"), /isn't right/);
  assert.match(m("ExpiredCodeException"), /expired/);
  assert.match(m("LimitExceededException"), /Too many/);
  assert.match(m("TooManyRequestsException"), /Too many/);
  assert.strictEqual(m("InvalidPasswordException", "Password does not conform to policy: too short"), "Password does not conform to policy: too short");
  assert.match(m("InvalidParameterException"), /temporary password from your invitation/);
  assert.match(m("NotAuthorizedException"), /email us/);
  assert.strictEqual(m("Whatever", "Network error"), "Network error");
  assert.match(ctx.passwordResetMessage(null), /Something went wrong/);
});

test("sendResetCode treats an unknown email like a known one, but still reports real failures", async () => {
  const unknown = Object.assign(new Error("nope"), { code: "UserNotFoundException" });
  const limit = Object.assign(new Error("slow down"), { code: "LimitExceededException" });
  let behaviour = "ok";
  const ctx = runSlice("async function sendResetCode", 'document.getElementById("forgot-open-btn")', {
    resetEmail: "a@example.com",
    requestPasswordReset: async () => { if (behaviour === "unknown") throw unknown; if (behaviour === "limit") throw limit; },
  });
  await ctx.sendResetCode();
  behaviour = "unknown";
  await ctx.sendResetCode(); // no error, so the page cannot be used to find out who has an account
  behaviour = "limit";
  await assert.rejects(() => ctx.sendResetCode(), (e) => e.code === "LimitExceededException");
});

test("login.js: the new password is checked before the service is called, and success returns to the log-in form with a notice", () => {
  const i = loginJs.indexOf('forgotConfirmForm.addEventListener("submit"');
  const block = loginJs.slice(i);
  assert.ok(block.indexOf("newPasswordProblem(") < block.indexOf("confirmPasswordReset("), "mismatched or short passwords never reach the service");
  assert.match(block, /confirmPasswordReset\(resetEmail, document\.getElementById\("forgot-code"\)\.value\.trim\(\), password\)/);
  assert.match(block, /backToLogin\("Your password has been changed\. Log in with your new password\."\)/);
});

test("login.js: the reset flow never stores the code or the passwords anywhere", () => {
  const block = loginJs.slice(loginJs.indexOf("// ---- Forgot password"));
  for (const bad of ["localStorage", "sessionStorage", "console.", "fetch(", "authedFetch("]) assert.ok(!block.includes(bad), `reset flow must not use ${bad}`);
});

// ---- feedback ----
test("the dashboard has a feedback card with an email link that carries no personal data", () => {
  assert.match(loginHtml, /<div class="card span-2 feedback-card" id="feedback-card">/);
  const link = loginHtml.match(/<a id="feedback-link"[^>]*href="([^"]+)"/)[1].replace(/&amp;/g, "&");
  assert.match(link, /^mailto:yovanarathbone@creatingtomorrow\.net\?subject=Career%20Profile%20beta%20feedback&body=/);
  const body = decodeURIComponent(link.split("&body=")[1]);
  assert.match(body, /What were you trying to do\?/);
  assert.match(body, /What happened\?/);
  assert.match(body, /What did you expect\?/);
  assert.ok(!/@|password/i.test(body), "the pre-filled message holds no email address or password");
});

test("the feedback card sits above Your Data, inside the dashboard, and asks people not to send passwords", () => {
  assert.ok(loginHtml.indexOf('id="feedback-card"') < loginHtml.indexOf('id="your-data-card"'));
  assert.match(loginHtml, /Please don't include passwords or private details/);
});

test("the address used for feedback and help is the one on the Contact page", () => {
  const contact = read("contact.html").match(/mailto:([^"]+)"/)[1];
  assert.strictEqual(contact, "yovanarathbone@creatingtomorrow.net");
  for (const m of loginHtml.matchAll(/mailto:([^?"]+)/g)) assert.strictEqual(m[1], contact);
});
