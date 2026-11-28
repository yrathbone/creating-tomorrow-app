// See your progress: Job scans, Resumes built, Applications and Skills, in that order. Skills is no longer a My Career tile.
const test = require("node:test");
const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");

const FRONTEND = path.join(__dirname, "..", "..", "..", "frontend");
const read = (...p) => fs.readFileSync(path.join(FRONTEND, ...p), "utf8");
const html = read("career", "login.html");
const loginJs = read("career", "login.js");

test("See your progress lists Job scans, Resumes built, Applications and Skills, in that order", () => {
  const profile = loginJs.slice(loginJs.indexOf("const profileStats = ["), loginJs.indexOf("];", loginJs.indexOf("const profileStats = [")));
  const activity = loginJs.slice(loginJs.indexOf("const activityStats = ["), loginJs.indexOf("];", loginJs.indexOf("const activityStats = [")));
  assert.ok(!profile.includes('key: "skills"'), "Skills is no longer a My Career tile");
  const keys = [...activity.matchAll(/key: "([a-z]+)"/g)].map((m) => m[1]);
  assert.deepStrictEqual(keys, ["history", "resumes", "applications", "skills"]);
  assert.match(activity, /"Job scan" : "Job scans"/);
  assert.ok(!loginJs.includes("Job & Skill Scan"), "the old scan label is gone");
});

test("the Skills panel sits in See your progress, after the Applications panel, and the scan heading is renamed", () => {
  const panels = html.indexOf('id="activity-panels"');
  const skills = html.indexOf('id="panel-skills"');
  const feedback = html.indexOf('id="feedback-card"');
  assert.ok(panels > 0 && panels < skills && skills < feedback, "the Skills panel is inside See your progress");
  assert.ok(html.indexOf('id="panel-applications"') < skills, "after Applications");
  assert.ok(html.includes("Job scan history"), "the scan panel heading says Job scan history");
  assert.ok(!html.includes("Job &amp; Skill Scan History"));
});
