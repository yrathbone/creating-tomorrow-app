// Priority 1, PR A: the evidence summary at the keyword step. The grouping is a pure function of what the keyword check returns, every status is an
// icon plus a word (never a colour alone), and the new styles add no colour. Static and VM checks; fictional data.
const test = require("node:test");
const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const FRONTEND = path.join(__dirname, "..", "..", "..", "frontend");
const read = (...p) => fs.readFileSync(path.join(FRONTEND, ...p), "utf8");

function load() {
  const made = [];
  const el = (tag) => {
    const node = { tag, className: "", textContent: "", children: [], attrs: {}, setAttribute(k, v) { this.attrs[k] = v; }, appendChild(c) { this.children.push(c); return c; } };
    made.push(node);
    return node;
  };
  const sandbox = { document: { createElement: el, createTextNode: (t) => ({ text: t }) } };
  vm.createContext(sandbox);
  vm.runInContext(read("career", "js", "evidenceView.js") + "\nthis.api = { EVIDENCE_CHIPS, evidenceChip, groupEvidence, renderEvidenceTiles };", sandbox);
  // plain objects from the VM have another realm's prototypes: copy them so deepStrictEqual compares values
  const plain = (value) => JSON.parse(JSON.stringify(value));
  return { ...sandbox.api, groupEvidence: (data) => plain(sandbox.api.groupEvidence(data)) };
}

const RESPONSE = {
  covered_exact: [{ term: "De-escalation", importance: "required" }, { term: "Scheduling", importance: "required" }],
  covered_related: [{ term: "Complaint resolution", importance: "required", evidence: "Handled complaints" }],
  alternatives_met: [{ terms: ["Certificate", "Experience"], importance: "required", met_by: "Certificate", evidence: "" }],
  terms: [
    { term: "Customer success", support: "transferable", evidence: "adjacent" },
    { term: "Salesforce or HubSpot", support: "none", alternatives: ["Salesforce", "HubSpot"] },
    { term: "Ticketing software", support: "none" },
    { term: "SaaS experience", support: "none" },
  ],
};

test("the grouping counts the five tiles from what the keyword check returned", () => {
  const { groupEvidence } = load();
  const g = groupEvidence(RESPONSE);
  assert.deepStrictEqual(g.tiles.map((t) => [t.key, t.count]), [["backed", 2], ["other", 1], ["alternative", 1], ["question", 2], ["none", 2]]);
});

test("an alternatives group and a different activity are questions; a term with no evidence is not evidenced; each keeps its place in the list", () => {
  const { groupEvidence } = load();
  const g = groupEvidence(RESPONSE);
  assert.deepStrictEqual(g.questions.map((x) => [x.term.term, x.index]), [["Customer success", 0], ["Salesforce or HubSpot", 1]]);
  assert.deepStrictEqual(g.notEvidenced.map((x) => [x.term.term, x.index]), [["Ticketing software", 2], ["SaaS experience", 3]]);
});

test("an empty or missing response groups to zeros and never throws", () => {
  const { groupEvidence } = load();
  for (const data of [undefined, null, {}, { terms: [] }]) {
    assert.deepStrictEqual(groupEvidence(data).tiles.map((t) => t.count), [0, 0, 0, 0, 0]);
  }
});

test("nothing is promoted: a term the check asked about never lands in a backed group", () => {
  const { groupEvidence } = load();
  const g = groupEvidence({ terms: [{ term: "Salesforce", support: "none" }], covered_exact: [], covered_related: [] });
  assert.deepStrictEqual(g.tiles.slice(0, 3).map((t) => t.count), [0, 0, 0]);
});

test("every status chip is an icon plus a word, with the icon hidden from screen readers", () => {
  const { EVIDENCE_CHIPS, evidenceChip } = load();
  for (const kind of Object.keys(EVIDENCE_CHIPS)) {
    const chip = evidenceChip(kind);
    assert.match(chip.className, new RegExp("evidence-chip-" + EVIDENCE_CHIPS[kind].cls));
    assert.strictEqual(chip.children[0].attrs["aria-hidden"], "true");
    assert.ok(chip.children[0].textContent.length > 0, "an icon");
    assert.match(chip.children[1].text, /^ [A-Z][a-z]+/, "a word");
  }
  assert.deepStrictEqual(Object.values(EVIDENCE_CHIPS).map((c) => c.word), ["Backed", "Other words", "One question", "Not evidenced"]);
});

test("the tiles list gets one item per count, each a number and a text label", () => {
  const { groupEvidence, renderEvidenceTiles } = load();
  const list = { children: [], textContent: "x", appendChild(c) { this.children.push(c); } };
  renderEvidenceTiles(list, groupEvidence(RESPONSE).tiles);
  assert.strictEqual(list.children.length, 5);
  assert.deepStrictEqual(list.children.map((li) => li.children[0].textContent), ["2", "1", "1", "2", "2"]);
  assert.ok(list.children.every((li) => li.children[1].textContent.length > 5), "a label under every count");
});

test("the page loads the evidence view before jobMatch.js, has the legend with icon and word chips, and the keyword step uses the view", () => {
  const html = read("career", "login.html");
  assert.ok(html.indexOf("js/evidenceView.js") > 0 && html.indexOf("js/evidenceView.js") < html.indexOf("js/jobMatch.js"));
  const legend = html.slice(html.indexOf('class="evidence-legend"'), html.indexOf('id="job-keywords-covered"'));
  for (const word of ["Backed", "Other words", "One question", "Not evidenced"]) assert.ok(legend.includes("</span> " + word + "</span>"), word);
  assert.ok(html.includes('id="job-keywords-tiles"'));
  const js = read("career", "js", "jobMatch.js");
  for (const needle of ["groupEvidence(", "renderEvidenceTiles(", "evidenceChip("]) assert.ok(js.includes(needle), needle);
  assert.ok(js.includes("#job-keywords-list .question-card"), "Save my choices still reads the cards from the same list");
});

test("the new styles use only the site's colours: no new hex values or font families, and the chips differ by outline as well as hue", () => {
  const css = read("career", "dashboard-v8.css");
  const block = css.slice(css.indexOf("the evidence summary at the keyword step"));
  assert.ok(block.length > 500, "found the block");
  assert.ok(!/#[0-9a-fA-F]{3,6}\b/.test(block), "no hex colours");
  assert.ok(!/font-family/.test(block), "no font family");
  for (const line of block.split(/\r?\n/).filter((l) => /\{/.test(l) && !l.startsWith("@media") && !l.startsWith("/*"))) {
    assert.ok(line.trim().startsWith("body.chrome-v6.dashboard-v4"), line);
  }
  assert.match(block, /evidence-chip-question \{ border: 2px solid var\(--c6-gold\)/); // thicker, gold-edged
  assert.match(block, /evidence-chip-other \{ background: rgba/); // filled
  assert.match(block, /evidence-chip \{[^}]*font-size: 0\.8125rem/); // 13px, above the 12px floor
});
