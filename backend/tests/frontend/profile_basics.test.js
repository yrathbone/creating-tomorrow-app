// Phase 2B: the saved name/contact line prefill the existing resume header inputs.
// Runs the real frontend/career/js/profileBasics.js in a bare VM with stub inputs and a stub
// authedFetch - no browser needed.  Run:  node --test backend/tests/frontend
const test = require("node:test");
const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const FRONTEND = path.join(__dirname, "..", "..", "..", "frontend", "career", "js");
const source = fs.readFileSync(path.join(FRONTEND, "profileBasics.js"), "utf8");

function load(fetchImpl) {
  const calls = [];
  const sandbox = {
    authedFetch: async (url, opts) => { calls.push({ url, opts }); return fetchImpl(url, opts); },
  };
  vm.createContext(sandbox);
  vm.runInContext(source, sandbox);
  return { sandbox, calls };
}
const ok = (body) => async () => ({ ok: true, json: async () => body });
const input = (value = "") => ({ value });

test("loads from GET /api/career/profile (no id of any kind is sent) and prefills empty inputs", async () => {
  const { sandbox, calls } = load(ok({ display_name: "Ada Lovelace", contact_line: "London | ada@example.com" }));
  await sandbox.loadProfileBasics();
  assert.strictEqual(calls.length, 1);
  assert.strictEqual(calls[0].url, "/api/career/profile");
  assert.ok(!calls[0].opts || !calls[0].opts.method || calls[0].opts.method === "GET");
  const name = input(), contact = input();
  sandbox.prefillResumeHeader(name, contact);
  assert.strictEqual(name.value, "Ada Lovelace");
  assert.strictEqual(contact.value, "London | ada@example.com");
});

test("never overwrites what the person already typed", async () => {
  const { sandbox } = load(ok({ display_name: "Saved Name", contact_line: "Saved contact" }));
  await sandbox.loadProfileBasics();
  const name = input("Typed Name"), contact = input("   ");
  sandbox.prefillResumeHeader(name, contact);
  assert.strictEqual(name.value, "Typed Name");
  assert.strictEqual(contact.value, "Saved contact"); // whitespace-only counts as empty
});

test("nothing saved means the inputs stay empty", async () => {
  const { sandbox } = load(ok({ display_name: null, contact_line: null }));
  await sandbox.loadProfileBasics();
  const name = input(), contact = input();
  sandbox.prefillResumeHeader(name, contact);
  assert.strictEqual(name.value, "");
  assert.strictEqual(contact.value, "");
});

test("a failed or unavailable profile (503 before the upgrade, network error) never breaks the dashboard", async () => {
  for (const impl of [async () => ({ ok: false, status: 503, json: async () => ({}) }), async () => { throw new Error("offline"); }]) {
    const { sandbox } = load(impl);
    await assert.doesNotReject(sandbox.loadProfileBasics());
    const name = input(), contact = input();
    sandbox.prefillResumeHeader(name, contact);
    assert.strictEqual(name.value + contact.value, "");
  }
});

test("missing inputs are tolerated", async () => {
  const { sandbox } = load(ok({ display_name: "A", contact_line: "B" }));
  await sandbox.loadProfileBasics();
  assert.doesNotThrow(() => sandbox.prefillResumeHeader(null, null));
});

test("both resume flows are wired to the stored values and still read the same inputs to build", () => {
  const general = fs.readFileSync(path.join(FRONTEND, "generalResume.js"), "utf8");
  const job = fs.readFileSync(path.join(FRONTEND, "jobMatch.js"), "utf8");
  assert.match(general, /prefillResumeHeader\(document\.getElementById\("general-resume-name"\), document\.getElementById\("general-resume-contact"\)\)/);
  assert.match(job, /prefillResumeHeader\(document\.getElementById\("job-build-name"\), document\.getElementById\("job-build-contact"\)\)/);
  // unchanged generation behavior: the request still sends whatever is in the inputs
  assert.match(general, /const name = document\.getElementById\("general-resume-name"\)\.value\.trim\(\);/);
  assert.match(general, /body: JSON\.stringify\(\{ name, contact \}\)/);
  assert.match(job, /const name = document\.getElementById\("job-build-name"\)\.value\.trim\(\);/);
  const page = fs.readFileSync(path.join(FRONTEND, "..", "login.html"), "utf8");
  assert.ok(page.indexOf("js/profileBasics.js") > page.indexOf("login.js") && page.indexOf("js/profileBasics.js") < page.indexOf("js/generalResume.js"));
  const login = fs.readFileSync(path.join(FRONTEND, "..", "login.js"), "utf8");
  assert.match(login, /await loadProfileBasics\(\)/);
});
