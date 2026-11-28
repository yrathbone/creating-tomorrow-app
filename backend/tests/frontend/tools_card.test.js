// The Your tools card: it sits under My Career and above the workspace cards, its three tiles open their own
// link panels, and each link presses a control that already exists on the dashboard.
const test = require("node:test");
const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");

const FRONTEND = path.join(__dirname, "..", "..", "..", "frontend");
const read = (...p) => fs.readFileSync(path.join(FRONTEND, ...p), "utf8");
const html = read("career", "login.html");
const loginJs = read("career", "login.js");
const nextStepJs = read("career", "js", "nextStep.js");
const css = read("career", "dashboard-v8.css");

test("Your tools sits under My Career, above See your progress and the workspace cards, and holds the next step", () => {
  const my = html.indexOf('class="card span-2 snapshot-card profile-card"');
  const tools = html.indexOf('id="tools-card"');
  const activity = html.indexOf('class="card span-2 snapshot-card activity-card"');
  const job = html.indexOf('class="card span-2 job-card"');
  assert.ok(my > 0 && my < tools && tools < activity && activity < job, "order: My Career, Your tools, See your progress, then the workspace cards");
  assert.match(html.slice(tools, activity), /<section class="next-step" id="next-step"/);
});

test("each tool tile opens its own panel, and each link presses a control that already exists", () => {
  const tiles = [...html.matchAll(/class="stat-card[^"]*tool-tile"[^>]*data-panel="([^"]+)"/g)].map((m) => m[1]);
  assert.deepStrictEqual(tiles, ["tools-profile", "tools-resumes", "tools-jobs"]);
  for (const key of tiles) assert.ok(html.includes(`id="panel-${key}"`), `panel-${key}`);
  const targets = [...html.matchAll(/data-tool-target="([^"]+)"/g)].map((m) => m[1]);
  assert.ok(targets.length >= 5, "the panels carry their links");
  for (const id of targets) assert.ok(html.includes(`id="${id}"`), `${id} exists`);
  assert.ok(html.includes('data-open-panel="resumes"') && html.includes('id="panel-resumes"'), "View resumes opens the resumes list");
  assert.match(loginJs, /"tools-stat-row"/);
  assert.match(loginJs, /document\.getElementById\("tools-card"\)\.addEventListener\("click"/);
});

test("the upload button and its next step share the name Manage career profile, and Showcase's button is gold", () => {
  assert.match(html, /id="upload-resume-btn" class="btn-primary">Manage career profile</);
  assert.match(nextStepJs, /button: "Manage career profile", targets: \["#upload-resume-btn"\]/);
  assert.match(html, /id="general-resume-start-btn" class="btn-gold"/);
  assert.match(nextStepJs, /targets: \["#general-resume-start-btn"\]/);
  assert.ok(!html.includes('id="general-resume-hero-btn"'), "the hero no longer has a general resume button");
});

test("the tools row fits its tiles across at every width", () => {
  assert.match(css, /\.tools-card \.stat-row\.tools-row \{ grid-template-columns: repeat\(auto-fit, minmax\(140px, 1fr\)\);/);
});

test("the LinkedIn tile is one of the tools, not part of See your progress", () => {
  const tools = html.slice(html.indexOf('id="tools-stat-row"'), html.indexOf('id="tools-panels"'));
  assert.match(tools, /<a class="stat-card stat-linkedin tool-tile" href="\.\.\/spotlight\.html">/);
  assert.doesNotMatch(loginJs, /stat-linkedin/, "login.js no longer adds a LinkedIn tile to See your progress");
  const activity = html.slice(html.indexOf('id="activity-stat-row"'), html.indexOf('id="activity-panels"'));
  assert.doesNotMatch(activity, /stat-linkedin/);
});
