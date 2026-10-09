// The two profile downloads: a readable Word copy (for people) and the full data backup (for restoring).
// Run:  node --test backend/tests/frontend
const test = require("node:test");
const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const FRONTEND = path.join(__dirname, "..", "..", "..", "frontend");
const read = (...p) => fs.readFileSync(path.join(FRONTEND, ...p), "utf8");
const html = read("career", "login.html");
const js = read("career", "login.js");

// Only the download code of login.js is run, with a stand-in page, server and file saver.
function loadDownloads(serverReply) {
  const start = js.indexOf("// Hands a finished file to the browser's Downloads.");
  const end = js.indexOf("function showConsentStep()");
  assert.ok(start > 0 && end > start, "the download code is where the test expects it");
  const handlers = {};
  const errorEl = { hidden: true, textContent: "" };
  const buttons = {};
  for (const id of ["export-readable-btn", "export-profile-btn"]) {
    buttons[id] = { disabled: false, addEventListener(type, fn) { handlers[id] = fn; } };
  }
  const saved = [];
  const fetched = [];
  const sandbox = {
    document: {
      getElementById: (id) => (id === "export-profile-error" ? errorEl : buttons[id]),
      createElement: () => ({ click() { saved.push({ href: this.href, name: this.download }); }, remove() {} }),
      body: { appendChild() {} },
    },
    URL: { createObjectURL: (blob) => { sandbox.lastBlob = blob; return "blob:test"; }, revokeObjectURL() {} },
    Blob: class { constructor(parts, opts) { this.parts = parts; this.type = (opts || {}).type; } },
    JSON, Date,
    formatErrorDetail: (detail, fallback) => detail || fallback,
    authedFetch: async (url) => { fetched.push(url); return serverReply(url); },
  };
  vm.createContext(sandbox);
  vm.runInContext(js.slice(start, end), sandbox);
  return { handlers, errorEl, buttons, saved, fetched, sandbox };
}

const ok = (extra) => Object.assign({ ok: true, status: 200 }, extra);
const today = new Date().toISOString().slice(0, 10);

test("the dashboard offers both downloads, clearly named, with a plain explanation", () => {
  assert.match(html, /id="export-readable-btn"[^>]*>Download a readable copy \(Word\)<\/button>/);
  assert.match(html, /id="export-profile-btn"[^>]*>Download full data backup \(\.json\)<\/button>/);
  assert.match(html, /The readable copy is for you to read, print or share\. The data backup is the complete technical file/);
});

test("the delete panel offers both copies before anything is erased", () => {
  assert.match(html, /id="delete-readable-btn"[^>]*>Download a readable copy \(Word\)<\/button>/);
  assert.match(html, /id="delete-backup-btn"[^>]*>Download full data backup \(\.json\)<\/button>/);
});

test("the readable button asks for the Word copy and saves it as a .docx, untouched", async () => {
  const w = loadDownloads(() => ok({ blob: async () => ({ kind: "docx-bytes" }) }));
  await w.handlers["export-readable-btn"]({ currentTarget: w.buttons["export-readable-btn"] });
  assert.deepStrictEqual(w.fetched, ["/api/career/export/readable"]);
  assert.strictEqual(w.saved.length, 1);
  assert.strictEqual(w.saved[0].name, `My_Career_Profile_${today}.docx`);
  assert.deepStrictEqual({ ...w.sandbox.lastBlob }, { kind: "docx-bytes" }, "the file the server built is saved as it came");
  assert.strictEqual(w.errorEl.hidden, true);
  assert.strictEqual(w.buttons["export-readable-btn"].disabled, false, "the button works again afterwards");
});

test("the data button still saves the full snapshot as indented JSON", async () => {
  const w = loadDownloads(() => ok({ json: async () => ({ experiences: [{ title: "Role" }] }) }));
  await w.handlers["export-profile-btn"]({ currentTarget: w.buttons["export-profile-btn"] });
  assert.deepStrictEqual(w.fetched, ["/api/career/export"]);
  assert.strictEqual(w.saved[0].name, `career_profile_data_backup_${today}.json`);
  assert.strictEqual(w.sandbox.lastBlob.type, "application/json");
  assert.deepStrictEqual(JSON.parse(w.sandbox.lastBlob.parts[0]), { experiences: [{ title: "Role" }] });
});

test("a failed download saves nothing, says why, and re-enables the button", async () => {
  const w = loadDownloads(() => ({ ok: false, status: 500, json: async () => ({ detail: "We couldn't build your readable copy. Please try again." }) }));
  await w.handlers["export-readable-btn"]({ currentTarget: w.buttons["export-readable-btn"] });
  assert.strictEqual(w.saved.length, 0);
  assert.strictEqual(w.errorEl.hidden, false);
  assert.match(w.errorEl.textContent, /couldn't build your readable copy/);
  assert.strictEqual(w.buttons["export-readable-btn"].disabled, false);
});

test("a second try clears the earlier error", async () => {
  let fail = true;
  const w = loadDownloads(() => (fail ? { ok: false, status: 500, json: async () => ({}) } : ok({ blob: async () => ({}) })));
  await w.handlers["export-readable-btn"]({ currentTarget: w.buttons["export-readable-btn"] });
  assert.strictEqual(w.errorEl.hidden, false);
  fail = false;
  await w.handlers["export-readable-btn"]({ currentTarget: w.buttons["export-readable-btn"] });
  assert.strictEqual(w.errorEl.hidden, true);
  assert.strictEqual(w.saved.length, 1);
});
