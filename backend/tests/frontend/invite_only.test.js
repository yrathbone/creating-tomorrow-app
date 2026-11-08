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

// ---- the invitation page (Option B: information only, no form) ----
const REGISTER_PAGE = () => read("career", "register.html");
const textOf = (html) => html.replace(/<script[\s\S]*?<\/script>|<style[\s\S]*?<\/style>/g, " ").replace(/<[^>]+>/g, " ").replace(/&rsquo;/g, "\u2019").replace(/&amp;/g, "&").replace(/\s+/g, " ").trim();

test("the invitation page is information only: no form, no inputs, no buttons, no scripts, and register.js is gone", () => {
  const html = REGISTER_PAGE();
  assert.ok(!/<form\b|<input\b|<button\b|<textarea\b|<select\b/i.test(html), "no form controls");
  assert.ok(!/<script\b/i.test(html), "no scripts (nothing here talks to a server)");
  assert.ok(!fs.existsSync(path.join(FRONTEND, "career", "register.js")), "career/register.js was removed with the form");
});

test("the invitation page uses the approved wording and no account-creation labels", () => {
  const html = REGISTER_PAGE();
  assert.match(html, /<title>Join Creating Tomorrow<\/title>/);
  assert.match(html, /<meta name="description" content="Creating Tomorrow is in a limited testing phase while we work to make our tools reliable, accessible, and helpful\." \/>/);
  assert.strictEqual((html.match(/<h1>/g) || []).length, 1);
  assert.match(html, /<h1>Join Creating Tomorrow<\/h1>/);
  const text = textOf(html);
  assert.ok(text.includes("We\u2019re currently welcoming participants by invitation."), text);
  assert.ok(text.includes("Creating Tomorrow is in a limited testing phase while we work to make our tools reliable, accessible, and helpful."));
  assert.ok(text.includes("Already received an invitation? Sign in to get started."));
  for (const gone of ["Create an account", "Create account", "Create a Creating Tomorrow account", "Career Profile is by invitation", "step-signup", "signup-"]) assert.ok(!html.includes(gone), `still present: ${gone}`);
  assert.ok(!/password|e-?mail address/i.test(text), "the page does not ask for or mention a password or email address to type");
});

test("the two actions are real links: Sign in goes to the sign-in page; Request an invitation opens the existing invitation-contact address (nothing is collected here)", () => {
  const html = REGISTER_PAGE();
  const links = [...html.matchAll(/<a class="(btn-primary|btn-secondary)" href="([^"]+)">([^<]+)<\/a>/g)].map((m) => ({ cls: m[1], href: m[2], label: m[3] }));
  assert.deepStrictEqual(links, [
    { cls: "btn-primary", href: "login.html", label: "Sign in" },
    { cls: "btn-secondary", href: "mailto:yovanarathbone@creatingtomorrow.net?subject=Career%20Profile%20beta%20invitation%20request", label: "Request an invitation" },
  ]);
  assert.ok(html.indexOf(">Sign in</a>") < html.indexOf(">Request an invitation</a>"), "Sign in comes first");
  assert.ok(html.indexOf("Already received an invitation?") < html.indexOf(">Sign in</a>"), "the guidance comes before the actions");
});

test("the invitation page keeps the site navigation and the footer links (keyboard and screen-reader users still have a way around)", () => {
  const html = REGISTER_PAGE();
  assert.match(html, /<nav class="site-nav">/);
  for (const href of ["../index.html", "../learn.html", "../videos.html", "../about.html", "login.html", "../tool.html"]) assert.ok(html.includes(`<a href="${href}"`) || html.includes(`href="${href}"`), `nav link ${href}`);
  assert.match(html, /<nav class="h5-footer-nav" aria-label="Footer">/);
  assert.match(html, /<main>/);
  assert.match(html, /<html lang="en">/);
  assert.match(html, /<meta name="robots" content="noindex" \/>/);
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

test("newPasswordProblem: at least 12 characters and both boxes must match", () => {
  const src = read("career", "login.js");
  const fn = src.slice(src.indexOf("function newPasswordProblem"), src.indexOf("loginForm.addEventListener"));
  const ctx = {};
  vm.createContext(ctx);
  vm.runInContext(fn, ctx);
  assert.strictEqual(ctx.newPasswordProblem("abcdefghijkl", "abcdefghijkl"), "");
  assert.match(ctx.newPasswordProblem("short", "short"), /at least 12 characters/);
  assert.match(ctx.newPasswordProblem("abcdefghijk", "abcdefghijk"), /at least 12 characters/); // 11 is still too short
  assert.match(ctx.newPasswordProblem("", ""), /at least 12 characters/);
  assert.match(ctx.newPasswordProblem("abcdefghijkl", "abcdefghijkx"), /don['’]t match/);
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

// ---- the sign-in page links to the invitation page (RP-0002 addendum 01) ----
const LOGIN_PAGE = () => read("career", "login.html");

test("the sign-in page has a clear link beneath the sign-in form to the invitation page", () => {
  const html = LOGIN_PAGE();
  const m = html.match(/<p class="login-help login-join">New to Creating Tomorrow\? We&rsquo;re currently welcoming participants by invitation\. <a href="register\.html">Learn how to join<\/a>\.<\/p>/);
  assert.ok(m, "the approved sentence and link are present, exactly once");
  assert.strictEqual((html.match(/Learn how to join/g) || []).length, 1);
  const step = html.slice(html.indexOf('id="step-login"'), html.indexOf('id="step-forgot"'));
  const iForm = step.indexOf("</form>");
  const iLink = step.indexOf("Learn how to join");
  assert.ok(iForm > 0 && iLink > iForm, "the link is after the sign-in form, inside the sign-in card");
  assert.ok(iLink < step.indexOf('id="login-error"'), "before the error area, which stays last");
  assert.ok(!/target=|aria-label=|rel=/.test(m[0]), "a plain same-tab link with its own visible text");
});

test("the link uses the correct relative path and both pages lead to each other (no dead end, no loop through scripts)", () => {
  const dir = path.join(FRONTEND, "career");
  assert.ok(fs.existsSync(path.join(dir, "register.html")), "register.html exists next to login.html");
  const toLogin = REGISTER_PAGE().match(/<a class="btn-primary" href="([^"]+)">Sign in<\/a>/)[1];
  assert.strictEqual(toLogin, "login.html");
  assert.ok(fs.existsSync(path.join(dir, toLogin)));
  for (const href of [...LOGIN_PAGE().matchAll(/href="(register\.html)"/g)].map((x) => x[1])) assert.ok(fs.existsSync(path.join(dir, href)), href);
});

test("sign-in and password recovery are untouched: the same forms, fields, buttons and panels exist, and login.js still drives them", () => {
  const html = LOGIN_PAGE();
  for (const id of ["login-form", "login-email", "login-password", "login-btn", "forgot-open-btn", "forgot-request-form", "forgot-email", "forgot-request-btn", "forgot-confirm-form", "forgot-code",
    "forgot-new-password", "forgot-new-password-confirm", "forgot-confirm-btn", "forgot-resend-btn", "forgot-back-btn", "forgot-error", "newpassword-form", "newpassword-input", "newpassword-confirm",
    "newpassword-btn", "newpassword-error", "login-error", "login-notice", "step-login", "step-forgot", "step-newpassword"]) assert.ok(html.includes(`id="${id}"`), id);
  assert.strictEqual((html.match(/<form\b/g) || []).length, 14, "no form was added or removed (the sign-in page has 14 forms, including the four sign-in and recovery forms, exactly as before)");
  assert.ok(html.indexOf('<p class="login-help"><button type="button" id="forgot-open-btn"') < html.indexOf("Learn how to join"), "Forgot your password stays directly beneath the form, before the new link");
  const js = read("career", "login.js");
  for (const needle of ["forgot-open-btn", "forgot-back-btn", "newpassword-form", "login-form"]) assert.ok(js.includes(needle), needle);
});

test("auth.js no longer says register.html loads the sign-in library", () => {
  const js = read("career", "js", "auth.js");
  assert.ok(!/register\.html/.test(js), "stale mention removed");
  assert.match(js, /script tag in login\.html /);
});

test("the two invitation-page buttons share one height rule and a visible keyboard focus indicator", () => {
  const css = read("career", "auth-v5.css").replace(/\/\*[\s\S]*?\*\//g, "");
  const rule = css.match(/body\.auth-v5 \.invite-actions a\s*\{([^}]*)\}/);
  assert.ok(rule, "one rule for both links");
  for (const need of [/box-sizing:\s*border-box/, /min-height:\s*3rem/, /display:\s*inline-flex/, /align-items:\s*center/, /border:\s*2px solid/, /margin-top:\s*0/]) assert.match(rule[1], need);
  const focus = css.match(/body\.auth-v5 \.invite-actions a:focus-visible\s*\{([^}]*)\}/);
  assert.ok(focus, "a focus-visible rule for both links");
  assert.match(focus[1], /outline:\s*3px solid #003395/);
  assert.match(focus[1], /outline-offset:\s*3px/);
  assert.ok(!/outline:\s*(none|0)/.test(css.match(/body\.auth-v5 \.invite-actions[^{]*\{[^}]*\}/g).join(" ")), "the focus indicator is never switched off");
});

test("narrow screens: the invitation actions wrap instead of overflowing, and the page adds no fixed widths", () => {
  const css = read("career", "auth-v5.css").replace(/\/\*[\s\S]*?\*\//g, "");
  const box = css.match(/body\.auth-v5 \.invite-actions\s*\{([^}]*)\}/)[1];
  assert.match(box, /display:\s*flex/);
  assert.match(box, /flex-wrap:\s*wrap/);
  assert.match(box, /gap:\s*0\.75rem\s*;/); // when the buttons stack on a narrow screen they keep a 12 px gap (not 4 px)
  const links = css.match(/body\.auth-v5 \.invite-actions a\s*\{([^}]*)\}/)[1];
  assert.ok(!/(^|[;\s])(width|min-width):\s*\d/.test(links), "no fixed width on the buttons");
});
