// The scanner-style ("ATS-style") score sits beside the Job Fit grade, so a result from Jobscan or a similar tool can be compared with a like-for-like number.
const test = require("node:test");
const assert = require("node:assert");
const fs = require("fs");
const path = require("path");

const FRONTEND = path.join(__dirname, "..", "..", "..", "frontend", "career");
const read = (...p) => fs.readFileSync(path.join(FRONTEND, ...p), "utf8");

test("the match-grade block has a line for the ATS-style score, hidden until a build returns one", () => {
  const html = read("login.html");
  const block = html.slice(html.indexOf('id="job-match-grade-block"'));
  assert.match(block.slice(0, 900), /<p id="job-ats-line" hidden><\/p>/);
});

test("jobMatch.js passes the build's ats_match to the grade and writes 'ATS-style score: N% (found of total ...)'", () => {
  const js = read("js", "jobMatch.js");
  assert.match(js, /renderMatchGrade\(data\.term_report \|\| \[\], data\.ats_match \|\| null\);/);
  assert.match(js, /function renderMatchGrade\(report, ats\)/);
  assert.match(js, /"ATS-style score: " \+ ats\.pct \+ "% \(" \+ ats\.found \+ " of " \+ ats\.total \+ " posting terms appear on this resume\)/);
  assert.match(js, /atsLine\.hidden = !\(ats && ats\.total\);/);
});
