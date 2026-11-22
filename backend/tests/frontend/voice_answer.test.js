// Speak-your-answer (resume interview): on-device only, explicit start/stop/cancel, typed answer always available.
// Runs the real frontend/career/js/voiceAnswer.js in a bare VM with a MOCKED recognition API. No microphone, no audio, no network.
// Run:  node --test backend/tests/frontend/voice_answer.test.js
const test = require("node:test");
const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const ROOT = path.join(__dirname, "..", "..", "..");
const SOURCE_PATH = path.join(ROOT, "frontend", "career", "js", "voiceAnswer.js");
const source = fs.readFileSync(SOURCE_PATH, "utf8");

function load() {
  const sandbox = {};
  sandbox.window = sandbox;
  vm.createContext(sandbox);
  vm.runInContext(source, sandbox);
  return sandbox.VoiceAnswer;
}

// A fake SpeechRecognition constructor. opts.keepLocal=false models a browser that ignores processLocally.
function fakeSR(opts = {}) {
  const log = { instances: [], starts: 0, stops: 0, aborts: 0, available: [], installs: [] };
  class FakeSR {
    constructor() {
      log.instances.push(this);
      this.lang = "";
      if (opts.keepLocal === false) {
        Object.defineProperty(this, "processLocally", { get: () => false, set: () => {} });
      } else {
        this.processLocally = false;
      }
    }
    start() { log.starts += 1; }
    stop() { log.stops += 1; }
    abort() { log.aborts += 1; }
  }
  FakeSR.available = async (o) => { log.available.push(o); return opts.status === undefined ? "available" : opts.status; };
  FakeSR.install = async (o) => { log.installs.push(o); return opts.installOk === undefined ? true : opts.installOk; };
  FakeSR.log = log;
  return FakeSR;
}

// Code only: full-line comments are removed so the rules are checked against what runs, not against prose.
const codeOnly = source.split("\n").filter((l) => !/^\s*\/\//.test(l)).join("\n");
// Objects made inside the VM have another prototype, so compare them as plain JSON.
const plain = (v) => JSON.parse(JSON.stringify(v));

test("the API is used only when unprefixed and complete (available and install present)", () => {
  const VA = load();
  assert.strictEqual(VA.getRecognitionCtor({}), null);
  assert.strictEqual(VA.getRecognitionCtor({ webkitSpeechRecognition: function () {} }), null, "prefixed-only is not used");
  const bare = function () {};
  assert.strictEqual(VA.getRecognitionCtor({ SpeechRecognition: bare }), null, "no available/install means no mic");
  const full = fakeSR();
  assert.strictEqual(VA.getRecognitionCtor({ SpeechRecognition: full }), full);
});

test("availability asks for on-device only (processLocally true) and passes status through", async () => {
  const VA = load();
  const SR = fakeSR({ status: "downloadable" });
  assert.strictEqual(await VA.checkOnDevice(SR, "en-US"), "downloadable");
  assert.deepStrictEqual(plain(SR.log.available[0]), { langs: ["en-US"], processLocally: true });
  assert.strictEqual(await VA.checkOnDevice(null, "en-US"), "unsupported");
  const broken = fakeSR();
  broken.available = () => Promise.reject(new Error("blocked"));
  assert.strictEqual(await VA.checkOnDevice(broken, "en-US"), "error");
});

test("installing a language pack is passed through and a refusal is reported as false", async () => {
  const VA = load();
  const SR = fakeSR({ installOk: true });
  assert.strictEqual(await VA.installPack(SR, "en-US"), true);
  assert.deepStrictEqual(plain(SR.log.installs[0]), { langs: ["en-US"] });
  const refused = fakeSR();
  refused.install = () => Promise.reject(new Error("NotAllowedError"));
  assert.strictEqual(await VA.installPack(refused, "en-US"), false);
});

test("nothing starts when the controller is created; only start() starts it", () => {
  const VA = load();
  const SR = fakeSR();
  VA.createVoiceInput({ SR, onState() {}, onFinal() {} });
  assert.strictEqual(SR.log.instances.length, 0);
  assert.strictEqual(SR.log.starts, 0);
});

test("start() sets processLocally true before starting, and starts exactly once", () => {
  const VA = load();
  const SR = fakeSR();
  const states = [];
  const c = VA.createVoiceInput({ SR, lang: "en-US", onState: (s) => states.push(s) });
  assert.strictEqual(c.start(), true);
  assert.strictEqual(SR.log.starts, 1);
  assert.strictEqual(SR.log.instances[0].processLocally, true);
  assert.strictEqual(SR.log.instances[0].lang, "en-US");
  assert.strictEqual(c.start(), false, "a second start while listening does nothing");
  assert.strictEqual(SR.log.starts, 1);
  assert.ok(states.includes("listening"));
});

test("no remote fallback: a browser that will not keep on-device mode is refused and never started", () => {
  const VA = load();
  const SR = fakeSR({ keepLocal: false });
  const states = [];
  const c = VA.createVoiceInput({ SR, onState: (s, m) => states.push([s, m]) });
  assert.strictEqual(c.start(), false);
  assert.strictEqual(SR.log.starts, 0, "rec.start() must never run without confirmed on-device mode");
  assert.match(states[states.length - 1][1], /not confirmed to run on this device/);
});

test("no API means no start and a typed-answer message", () => {
  const VA = load();
  const states = [];
  const c = VA.createVoiceInput({ SR: null, onState: (s, m) => states.push([s, m]) });
  assert.strictEqual(c.start(), false);
  assert.match(states[0][1], /You can type your answer instead/);
});

test("stop() ends listening and keeps the final text that was already heard", () => {
  const VA = load();
  const SR = fakeSR();
  const heard = [];
  const c = VA.createVoiceInput({ SR, onFinal: (t) => heard.push(t) });
  c.start();
  const rec = SR.log.instances[0];
  rec.onresult({ resultIndex: 0, results: [Object.assign([{ transcript: "I led a team" }], { isFinal: true })] });
  c.stop();
  assert.strictEqual(SR.log.stops, 1);
  assert.deepStrictEqual(heard, ["I led a team"]);
});

test("interim text is shown as a status, never appended", () => {
  const VA = load();
  const SR = fakeSR();
  const heard = [];
  const states = [];
  const c = VA.createVoiceInput({ SR, onFinal: (t) => heard.push(t), onState: (s, m) => states.push([s, m]) });
  c.start();
  SR.log.instances[0].onresult({ resultIndex: 0, results: [Object.assign([{ transcript: "I led" }], { isFinal: false })] });
  assert.deepStrictEqual(heard, []);
  assert.ok(states.some(([s, m]) => s === "listening" && /Hearing: I led/.test(m)));
});

test("cancel() aborts, and results that arrive afterwards are dropped", () => {
  const VA = load();
  const SR = fakeSR();
  const heard = [];
  const c = VA.createVoiceInput({ SR, onFinal: (t) => heard.push(t) });
  c.start();
  const rec = SR.log.instances[0];
  c.cancel();
  assert.strictEqual(SR.log.aborts, 1);
  rec.onresult({ resultIndex: 0, results: [Object.assign([{ transcript: "late words" }], { isFinal: true })] });
  assert.deepStrictEqual(heard, []);
  assert.strictEqual(c.isListening(), false);
});

test("errors give a plain message, and the controller does not restart by itself", () => {
  const VA = load();
  const SR = fakeSR();
  const states = [];
  const c = VA.createVoiceInput({ SR, onState: (s, m) => states.push([s, m]) });
  c.start();
  SR.log.instances[0].onerror({ error: "not-allowed" });
  assert.match(states[states.length - 1][1], /Microphone access was blocked/);
  assert.strictEqual(SR.log.starts, 1, "no automatic retry");
  assert.strictEqual(c.isListening(), false);
  c.start();
  SR.log.instances[1].onerror({ error: "language-not-supported" });
  assert.match(states[states.length - 1][1], /not available on this device/);
  assert.strictEqual(SR.log.starts, 2, "a new start only from a new click");
});

test("every error code has a typed-answer path in its message (except aborted)", () => {
  const VA = load();
  for (const code of ["not-allowed", "service-not-allowed", "no-speech", "audio-capture", "language-not-supported", "language-unavailable", "network", "other"]) {
    assert.match(VA.errorMessage(code), /type|typed|Try again/i, code);
  }
});

test("onend returns to idle without starting again", () => {
  const VA = load();
  const SR = fakeSR();
  const states = [];
  const c = VA.createVoiceInput({ SR, onState: (s) => states.push(s) });
  c.start();
  SR.log.instances[0].onend();
  assert.strictEqual(states[states.length - 1], "idle");
  assert.strictEqual(SR.log.starts, 1);
});

test("transcript is appended to the typed text; typed text is never removed", () => {
  const VA = load();
  assert.strictEqual(VA.appendTranscript("", "Hello there"), "Hello there");
  assert.strictEqual(VA.appendTranscript("I managed a store.  ", "We grew sales."), "I managed a store. We grew sales.");
  assert.strictEqual(VA.appendTranscript("Typed first", "   "), "Typed first");
  assert.strictEqual(VA.appendTranscript(null, "Spoken"), "Spoken");
});

test("the module makes no network request, records no audio and stores nothing", () => {
  for (const banned of ["fetch(", "XMLHttpRequest", "sendBeacon", "MediaRecorder", "getUserMedia", "new Blob", "localStorage", "sessionStorage", "indexedDB", "FormData", "WebSocket"]) {
    assert.ok(!codeOnly.includes(banned), "voiceAnswer.js code must not contain " + banned);
  }
});

test("the browser-default (remote) setting is never requested: processLocally is only ever set to true", () => {
  const sets = codeOnly.match(/processLocally\s*=\s*[^;]+/g) || [];
  assert.deepStrictEqual(sets, ["processLocally = true"]);
  assert.ok(!/processLocally:\s*false/.test(codeOnly), "no availability check with processLocally false");
});

test("no unverified size claim: the language-pack text never states a download size", () => {
  const rr = fs.readFileSync(path.join(ROOT, "frontend", "career", "js", "resumeReview.js"), "utf8");
  const html = fs.readFileSync(path.join(ROOT, "frontend", "career", "login.html"), "utf8");
  for (const text of [source, rr, html]) {
    assert.ok(!/\b\d+\s*MB\b/.test(text), "no megabyte figure");
  }
});

test("submit is explicit: Send answers and continue, with the disclosure immediately above it", () => {
  const html = fs.readFileSync(path.join(ROOT, "frontend", "career", "login.html"), "utf8");
  const disclosureAt = html.indexOf('id="resume-questions-disclosure"');
  const submitAt = html.indexOf('id="resume-questions-submit-btn"');
  assert.ok(disclosureAt > 0 && submitAt > disclosureAt, "disclosure comes before the submit button");
  const tail = html.slice(html.indexOf("</p>", disclosureAt), html.lastIndexOf("<button", submitAt));
  assert.ok(/^<\/p>\s*$/.test(tail), "only whitespace sits between the disclosure and the button");
  assert.match(html, /id="resume-questions-submit-btn">Send answers and continue<\/button>/);
  const disclosure = html.slice(disclosureAt, html.indexOf("</p>", disclosureAt));
  assert.match(disclosure, /AI service/);
  assert.match(disclosure, /spoken transcript/);
  assert.match(disclosure, /interview draft/);
  assert.match(disclosure, /discard the draft/);
});

test("after a successful save the in-memory answers and suggestions are cleared, and no browser storage holds interview answers", () => {
  const rr = fs.readFileSync(path.join(ROOT, "frontend", "career", "js", "resumeReview.js"), "utf8");
  const saveAt = rr.indexOf('document.getElementById("resume-save-btn").addEventListener');
  assert.ok(saveAt > 0, "save handler found");
  const saveBody = rr.slice(saveAt, rr.indexOf("saveBtn.disabled = false;", saveAt));
  assert.match(saveBody, /resumeState\.history = \[\];/, "answer history cleared after save");
  assert.match(saveBody, /resumeState\.discoveredFacts = \[\];/, "suggestions cleared after save");
  assert.match(saveBody, /currentResumeQuestions = \[\];/, "pending questions cleared after save");
  assert.match(saveBody, /resume-questions-list"\);\s*if \(questionsList\) questionsList\.replaceChildren\(\);/, "answer boxes removed after save");
  for (const f of ["resumeReview.js", "voiceAnswer.js"]) {
    const text = fs.readFileSync(path.join(ROOT, "frontend", "career", "js", f), "utf8");
    assert.ok(!/localStorage|sessionStorage|indexedDB/.test(text), f + " stores no answers in browser storage");
  }
});

test("raw answers are cleared at the analysis-to-review step, keeping the suggestions, and kept on a failed call so a retry is safe", () => {
  const rr = fs.readFileSync(path.join(ROOT, "frontend", "career", "js", "resumeReview.js"), "utf8");
  const start = rr.indexOf("async function submitResumeAnswers");
  const end = rr.indexOf("document.getElementById(\"resume-questions-submit-btn\")", start);
  const fn = rr.slice(start, end);
  const confirmAt = fn.indexOf('if (data.stage === "confirm")');
  const elseAt = fn.indexOf("} else {", confirmAt);
  const confirmBlock = fn.slice(confirmAt, elseAt);
  assert.ok(confirmAt > 0, "confirm branch found");
  assert.match(confirmBlock, /resumeState\.history = \[\];/, "answers cleared when suggestions arrive");
  assert.match(confirmBlock, /currentResumeQuestions = \[\];/);
  assert.match(confirmBlock, /replaceChildren\(\)/, "answer boxes removed at review");
  assert.match(confirmBlock, /resumeState\.discoveredFacts = data\.discovered_facts/, "suggestions kept");
  const catchAt = fn.indexOf("} catch (err) {");
  assert.ok(catchAt > 0, "error path found");
  assert.ok(!/history = \[\]/.test(fn.slice(catchAt)), "a failed call does not clear the answers");
});

test("the finish button is still there (it also sends answers, so the same disclosure covers it)", () => {
  const html = fs.readFileSync(path.join(ROOT, "frontend", "career", "login.html"), "utf8");
  assert.ok(html.indexOf('id="resume-questions-finish-btn"') > html.indexOf('id="resume-questions-submit-btn"'));
});

test("wiring: only the detail (free-text) answer gets the mic, and the page loads the module first", () => {
  const rr = fs.readFileSync(path.join(ROOT, "frontend", "career", "js", "resumeReview.js"), "utf8");
  const detailBlock = rr.slice(rr.indexOf('if (q.type === "detail")'), rr.indexOf("} else {", rr.indexOf('if (q.type === "detail")')));
  assert.match(detailBlock, /attachVoiceAnswer\(card, textarea\)/);
  const html = fs.readFileSync(path.join(ROOT, "frontend", "career", "login.html"), "utf8");
  assert.ok(html.indexOf("js/voiceAnswer.js") > 0 && html.indexOf("js/voiceAnswer.js") < html.indexOf("js/resumeReview.js"));
});
