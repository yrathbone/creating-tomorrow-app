// The resume layout menu: every screen that downloads a resume offers the same three layouts
// and sends the choice to the server. Static checks only.  Run:  node --test backend/tests/frontend
const test = require("node:test");
const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");

const FRONTEND = path.join(__dirname, "..", "..", "..", "frontend");
const read = (...p) => fs.readFileSync(path.join(FRONTEND, ...p), "utf8");
const LAYOUTS = ["classic", "modern", "traditional"];

function optionValues(html, selectId) {
  const m = html.match(new RegExp(`<select id="${selectId}">([\\s\\S]*?)</select>`));
  assert.ok(m, `missing select #${selectId}`);
  return [...m[1].matchAll(/<option value="([^"]+)"/g)].map((x) => x[1]);
}

test("the three public tools each have a layout menu next to the ATS checkbox, and send it", () => {
  for (const [page, js] of [["tool.html", "app.js"], ["scratch.html", "scratch.js"], ["elevate.html", "elevate.js"]]) {
    const html = read(page);
    assert.deepStrictEqual(optionValues(html, "resume-template"), LAYOUTS, page);
    assert.ok(html.indexOf('id="ats-mode"') < html.indexOf('id="resume-template"'), `${page}: menu follows the ATS checkbox`);
    assert.match(read(js), /template: document\.getElementById\("resume-template"\)\.value/, `${js} sends the layout`);
    assert.match(read(js), /ats_mode: atsMode/, `${js} still sends ATS mode`);
  }
});

test("the dashboard's two download screens have a layout menu and send it", () => {
  const html = read("career", "login.html");
  assert.deepStrictEqual(optionValues(html, "job-resume-template"), LAYOUTS);
  assert.deepStrictEqual(optionValues(html, "general-resume-template"), LAYOUTS);
  assert.ok(html.indexOf('id="job-resume-template"') < html.indexOf('id="job-download-btn"'));
  assert.ok(html.indexOf('id="general-resume-template"') < html.indexOf('id="general-resume-download-btn"'));
  assert.match(read("career", "js", "jobMatch.js"), /template: document\.getElementById\("job-resume-template"\)\.value/);
  assert.match(read("career", "js", "generalResume.js"), /template: document\.getElementById\("general-resume-template"\)\.value/);
});

test("old resumes can be downloaded again in any layout (a menu on each Resumes Built card)", () => {
  const js = read("career", "js", "history.js");
  const values = [...js.matchAll(/\["(classic|modern|traditional)", "/g)].map((m) => m[1]);
  assert.deepStrictEqual(values, LAYOUTS);
  assert.match(js, /download\?template=" \+ encodeURIComponent\(template \|\| "classic"\)/);
  assert.match(js, /downloadResumeVersion\(entry, \(entry\.resume_data \|\| \{\}\)\.name, layout\.value\)/);
});

test("the layout names the pages offer are exactly the ones the server knows", () => {
  const py = fs.readFileSync(path.join(__dirname, "..", "..", "resume_builder.py"), "utf8");
  const block = py.slice(py.indexOf("TEMPLATES = {"), py.indexOf("DEFAULT_TEMPLATE"));
  const serverNames = [...block.matchAll(/^    "([a-z]+)": \{/gm)].map((m) => m[1]);
  assert.deepStrictEqual(serverNames, LAYOUTS);
});
