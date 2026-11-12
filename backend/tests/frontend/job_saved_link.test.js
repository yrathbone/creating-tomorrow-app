// C-52: starting a comparison from a saved link must start clean. The real frontend/career/js/jobMatch.js runs in a bare VM
// with a permissive fake DOM. Nothing is sent anywhere; authedFetch is a stub that fails the test if it is called.
const test = require("node:test");
const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const FRONTEND = path.join(__dirname, "..", "..", "..", "frontend", "career");
const source = fs.readFileSync(path.join(FRONTEND, "js", "jobMatch.js"), "utf8");
// evidenceView.js loads before jobMatch.js on the real page and defines groupReport(), which the reset calls.
const evidenceSource = fs.readFileSync(path.join(FRONTEND, "js", "evidenceView.js"), "utf8");

function makeEl(id) {
  const el = {
    id, value: "", textContent: "", hidden: false, className: "", innerHTML: "", disabled: false, checked: false,
    children: [], dataset: {}, style: {}, listeners: {}, classList: { add() {}, remove() {}, toggle() {}, contains() { return false; } },
    addEventListener(type, fn) { (this.listeners[type] = this.listeners[type] || []).push(fn); },
    removeEventListener() {}, focus() { this.focused = true; }, blur() {}, reset() {}, scrollIntoView() {},
    appendChild(c) { this.children.push(c); return c; }, removeChild() {}, setAttribute() {}, removeAttribute() {},
    querySelector() { return makeEl("child"); }, querySelectorAll() { return []; }, getAttribute() { return null; },
    select() {}, closest() { return null; }, contains() { return false; }, insertBefore() {}, prepend() {},
  };
  return el;
}

function load() {
  const elements = {};
  const getEl = (id) => (elements[id] = elements[id] || makeEl(id));
  const sandbox = {
    console, setTimeout, clearTimeout, URL,
    document: {
      getElementById: getEl,
      createElement: (tag) => makeEl(tag),
      createTextNode: (t) => ({ textNode: t }),
      querySelector: () => makeEl("q"),
      querySelectorAll: () => [],
      addEventListener() {},
      activeElement: null,
      body: makeEl("body"),
    },
    window: { addEventListener() {}, scrollTo() {} },
    navigator: {},
    localStorage: { getItem() { return null; }, setItem() {}, removeItem() {} },
    authedFetch: async (url) => { throw new Error("no network in this test: " + url); },
    formatErrorDetail: (d, f) => f,
    escapeHtml: (s) => String(s),
    startProcessingState() {}, stopProcessingState() {}, makeTextField() { return makeEl("field"); },
    loadScanHistory() {}, loadResumeVersions() {}, loadSuggestions() {}, carryLayoutChoice() {},
    loadApplications() {}, restoreCurrentJobTarget() {}, approveOpportunityResume() {}, startJobFromOpportunity() {},
  };
  vm.createContext(sandbox);
  vm.runInContext(evidenceSource, sandbox);
  vm.runInContext(source, sandbox);
  return { sandbox, elements, getEl };
}

test("starting a comparison from a saved link clears the old pasted posting and the old comparison", () => {
  const { sandbox, getEl } = load();
  // A previous comparison left its text and results in place.
  getEl("job-description-input").value = "OLD POSTING: Senior Analyst at Other Company, 10 years required";
  vm.runInContext(`
    jobState.jobDescription = "OLD POSTING: Senior Analyst at Other Company, 10 years required";
    jobState.matchReport = { requirements: [{ text: "10 years" }] };
    jobState.resumeVersionId = 555;
    jobState.jobTitle = "Senior Analyst";
    jobState.tailoredResumeData = { name: "Old" };
    jobState.scanHistoryId = 42;
  `, sandbox);

  vm.runInContext(`startJobFromOpportunity({ id: 7, title: "Program Analyst (Example)", employer: "Northwind Example Co." })`, sandbox);

  assert.strictEqual(getEl("job-description-input").value, "", "pasted posting text is cleared");
  assert.strictEqual(vm.runInContext("jobState.jobDescription", sandbox), "");
  assert.strictEqual(vm.runInContext("jobState.matchReport", sandbox), null);
  assert.strictEqual(vm.runInContext("jobState.resumeVersionId", sandbox), null);
  assert.strictEqual(vm.runInContext("jobState.tailoredResumeData", sandbox), null);
  assert.strictEqual(vm.runInContext("jobState.scanHistoryId", sandbox), null);
  assert.strictEqual(vm.runInContext("jobState.opportunityId", sandbox), 7, "the new saved link is the one linked");
  assert.match(getEl("job-opportunity-context").textContent, /Program Analyst \(Example\) at Northwind Example Co\./);
  assert.strictEqual(getEl("job-opportunity-context").hidden, false);
  assert.strictEqual(getEl("job-input-state").hidden, false, "the paste box is shown for the new job");
});

test("a plain Add a job after a saved link is not linked to it", () => {
  const { sandbox, getEl } = load();
  vm.runInContext(`startJobFromOpportunity({ id: 7, title: "Program Analyst", employer: "Acme" })`, sandbox);
  getEl("job-target-add-btn").listeners.click[0]({ preventDefault() {} });
  assert.strictEqual(vm.runInContext("jobState.opportunityId", sandbox), null);
  assert.strictEqual(getEl("job-opportunity-context").hidden, true);
});
