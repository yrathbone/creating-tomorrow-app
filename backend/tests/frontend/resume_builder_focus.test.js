// Phase 02 batch 2.6A: keyboard focus and the "your resume is ready" announcement in the General Resume builder.
// Runs frontend/career/js/generalResume.js in a bare VM with stand-in page elements that record every focus() call and every
// change to the status text. This checks the page's DOM behavior and markup; it is NOT a screen-reader test.
// Run:  node --test backend/tests/frontend
const test = require("node:test");
const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const CAREER = path.join(__dirname, "..", "..", "..", "frontend", "career");
const read = (...p) => fs.readFileSync(path.join(CAREER, ...p), "utf8");

const IDS = ["general-resume-empty", "general-resume-form", "general-resume-loading", "general-resume-done", "general-resume-card", "general-resume-hero-btn",
  "general-resume-hero-btn-2", "general-resume-start-btn", "general-resume-cancel-btn", "general-resume-build-btn", "general-resume-name", "general-resume-contact",
  "general-resume-error", "general-resume-download-btn", "general-resume-template", "general-resume-again-btn", "general-build-layout", "general-download-msg",
  "general-resume-status", "general-resume-heading"];

function world({ buildFails = false } = {}) {
  const log = { focus: [], status: [], alerts: [], saved: [] };
  const els = {};
  const handlers = {};
  for (const id of IDS) {
    const handlerList = (handlers[id] = {});
    els[id] = {
      id, hidden: false, disabled: false, value: "", scrollIntoView() {},
      addEventListener(type, fn) { (handlerList[type] = handlerList[type] || []).push(fn); },
      focus(options) { log.focus.push({ id, options }); },
      fire(type, event = {}) { return Promise.all((handlerList[type] || []).map((fn) => fn(event))); },
    };
  }
  els["general-resume-error"].hidden = true;
  els["general-download-msg"].hidden = true;
  els["general-resume-template"].value = "classic";
  els["general-resume-name"].value = "María José Peña-Núñez";
  els["general-resume-contact"].value = "Naperville, IL";
  let statusText = "";
  Object.defineProperty(els["general-resume-status"], "textContent", { get: () => statusText, set: (v) => { statusText = v; log.status.push(v); } });
  let builds = 0;
  const sandbox = {
    document: { getElementById: (id) => els[id] || null, createElement: () => ({ click() { log.saved.push(this.download); }, remove() {} }), body: { appendChild() {} } },
    URL: { createObjectURL: () => "blob:x", revokeObjectURL() {} },
    alert: (m) => log.alerts.push(m),
    prefillResumeHeader() {}, confirmHeaderDetails: () => true, startProcessingState() {}, stopProcessingState() {}, carryLayoutChoice() {},
    formatErrorDetail: (detail, fallback) => (typeof detail === "string" && detail ? detail : fallback),
    authedFetch: async (url) => {
      if (/build-general-resume/.test(url)) {
        builds += 1;
        if (buildFails) return { ok: false, status: 503, json: async () => ({ detail: "We couldn't build your resume right now. Please try again." }) };
        return { ok: true, json: async () => ({ resume_data: { name: "María José Peña-Núñez", skills: ["A"] } }) };
      }
      return { ok: true, blob: async () => ({}) };
    },
  };
  vm.createContext(sandbox);
  vm.runInContext(read("js", "resumeDownload.js") + "\n" + read("js", "generalResume.js"), sandbox);
  return { els, log, builds: () => builds };
}
const focused = (w) => w.log.focus.map((f) => f.id);

// ---- markup ----------------------------------------------------------------------------------------------------------------
test("the ready message has a persistent polite status region, not an alert", () => {
  const html = read("login.html");
  const region = html.match(/<p id="general-resume-status"[^>]*>/);
  assert.ok(region, "status region missing");
  assert.match(region[0], /role="status"/);
  assert.match(region[0], /aria-live="polite"/);
  assert.match(region[0], /aria-atomic="true"/);
  assert.doesNotMatch(region[0], /\bhidden\b/); // always on the page, so a later change is announced
  assert.doesNotMatch(region[0], /role="alert"|aria-live="assertive"/);
  const card = html.slice(html.indexOf('id="general-resume-card"'), html.indexOf('class="card span-2 snapshot-card profile-card"'));
  assert.ok(card.indexOf("general-resume-status") < card.indexOf('id="general-resume-done"'), "the region must sit outside the panel that is shown and hidden");
  assert.strictEqual((card.match(/role="alert"/g) || []).length, 2); // only the two error messages are alerts
});

test("the card heading and the loading panel can receive focus from a script, and the build error is an alert", () => {
  const html = read("login.html");
  assert.match(html, /<h2 id="general-resume-heading" tabindex="-1">General Resume<\/h2>/);
  assert.match(html, /<div id="general-resume-loading"[^>]*tabindex="-1"/);
  assert.match(html, /<div id="general-resume-error" class="error" role="alert" hidden><\/div>/);
});

test("the screen-reader-only class and the heading focus ring are in the dashboard stylesheet and scoped to it", () => {
  const css = read("dashboard-v4.css");
  assert.match(css, /body\.dashboard-v4 \.sr-only \{[^}]*clip: rect\(0, 0, 0, 0\)[^}]*\}/);
  assert.match(css, /body\.dashboard-v4 #general-resume-heading:focus-visible \{ outline: 3px solid var\(--v4-blue\);/); // the solid blue, not the 22% see-through ring colour
});

// ---- focus -----------------------------------------------------------------------------------------------------------------
test("a keyboard press on Build a general resume puts focus in the name field; a mouse tap, a touch tap or the next-step shortcut does not", async () => {
  const pressedFromKeyboard = { currentTarget: { matches: (selector) => selector === ":focus-visible" } };
  const notFromKeyboard = { detail: 1, currentTarget: { matches: () => false } }; // mouse or touch tap, or a script's click()
  const keyboard = world();
  await keyboard.els["general-resume-start-btn"].fire("click", pressedFromKeyboard);
  assert.deepStrictEqual(focused(keyboard), ["general-resume-name"]);
  const other = world();
  await other.els["general-resume-start-btn"].fire("click", notFromKeyboard);
  await other.els["general-resume-hero-btn"].fire("click", notFromKeyboard);
  await other.els["general-resume-hero-btn-2"].fire("click", { detail: 0, currentTarget: { matches: () => false } }); // programmatic click
  assert.deepStrictEqual(focused(other), []); // no on-screen keyboard pops up on a phone
});

test("a successful build: focus goes to the loading panel, then to the card heading, and the ready message is announced once", async () => {
  const w = world();
  await w.els["general-resume-build-btn"].fire("click");
  assert.deepStrictEqual(focused(w), ["general-resume-loading", "general-resume-heading"]);
  assert.deepStrictEqual(w.log.status, ["", "Your general resume is ready."]);
  assert.strictEqual(w.els["general-resume-done"].hidden, false);
  assert.strictEqual(w.els["general-resume-error"].hidden, true);
  assert.ok(w.log.focus.every((f) => f.options && f.options.preventScroll === true)); // no jump of the page
  assert.deepStrictEqual(w.log.alerts, []);
});

test("a failed build: the error is shown, focus returns to the Build button, and nothing is announced as ready", async () => {
  const w = world({ buildFails: true });
  await w.els["general-resume-build-btn"].fire("click");
  assert.deepStrictEqual(focused(w), ["general-resume-loading", "general-resume-build-btn"]);
  assert.strictEqual(w.els["general-resume-error"].hidden, false);
  assert.match(w.els["general-resume-error"].textContent, /couldn't build your resume/);
  assert.strictEqual(w.els["general-resume-form"].hidden, false); // what the person typed is still there
  assert.strictEqual(w.els["general-resume-name"].value, "María José Peña-Núñez");
  assert.deepStrictEqual(w.log.status, [""]);
});

test("a missing name leaves focus exactly where it was and shows the message", async () => {
  const w = world();
  w.els["general-resume-name"].value = "";
  await w.els["general-resume-build-btn"].fire("click");
  assert.deepStrictEqual(focused(w), []);
  assert.strictEqual(w.els["general-resume-error"].hidden, false);
  assert.match(w.els["general-resume-error"].textContent, /name and a contact line/);
});

test("later builds announce again: the region is emptied when a build starts and on Build again", async () => {
  const w = world();
  await w.els["general-resume-build-btn"].fire("click");
  await w.els["general-resume-again-btn"].fire("click"); // Build again clears the typed name and contact line
  w.els["general-resume-name"].value = "María José Peña-Núñez";
  w.els["general-resume-contact"].value = "Naperville, IL";
  await w.els["general-resume-build-btn"].fire("click");
  assert.deepStrictEqual(w.log.status, ["", "Your general resume is ready.", "", "", "Your general resume is ready."]);
  assert.strictEqual(w.builds(), 2);
});

test("Build again and Cancel put focus back on the Build a general resume button", async () => {
  const w = world();
  await w.els["general-resume-build-btn"].fire("click");
  w.log.focus.length = 0;
  await w.els["general-resume-again-btn"].fire("click");
  assert.deepStrictEqual(focused(w), ["general-resume-start-btn"]);
  w.log.focus.length = 0;
  await w.els["general-resume-cancel-btn"].fire("click");
  assert.deepStrictEqual(focused(w), ["general-resume-start-btn"]);
});

test("repeated downloads never move focus or touch the status region", async () => {
  const w = world();
  await w.els["general-resume-build-btn"].fire("click");
  w.log.focus.length = 0;
  const before = w.log.status.length;
  await w.els["general-resume-download-btn"].fire("click");
  await w.els["general-resume-download-btn"].fire("click");
  assert.deepStrictEqual(w.log.saved, ["María_José_Peña-Núñez_Resume.docx", "María_José_Peña-Núñez_Resume.docx"]);
  assert.deepStrictEqual(focused(w), []);
  assert.strictEqual(w.log.status.length, before);
});
