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

test("Build My Resume and the resume 'working' screens use the brand crimson, with readable contrast, and layouts are untouched", () => {
  const css = read("dashboard-v4.css");
  assert.match(css, /button#job-build-btn#job-build-btn \{ background-image: none; background-color: #c8102e; color: #ffffff;/);
  assert.match(css, /button#job-build-btn#job-build-btn:hover:not\(:disabled\),[\s\S]*?\{ background-color: #8f0b22;/);
  for (const id of ["job-loading-state", "job-build-loading-state", "general-resume-loading", "resume-loading-state"]) {
    assert.ok(css.includes(`body.dashboard-v4 #${id} .processing-dot { background: #c8102e; }`) || css.includes(`#${id} .processing-dot,`), id + " dots");
    assert.ok(css.includes(`#${id} .processing-status`), id + " status text");
  }
  const lum = (h) => { const c = [0, 2, 4].map((i) => parseInt(h.slice(i, i + 2), 16) / 255).map((v) => (v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4))); return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]; };
  const ratio = (a, b) => { const [x, y] = [lum(a), lum(b)].sort((m, n) => n - m); return (x + 0.05) / (y + 0.05); };
  assert.ok(ratio("FFFFFF", "C8102E") >= 4.5, "white text on the crimson button");
  assert.ok(ratio("8F0B22", "FFFFFF") >= 7, "dark red wait text on white");
  // colours only: the new block sets no width, height, padding, margin, display or position
  const block = css.slice(css.indexOf("Build My Resume and the"));
  assert.ok(!/(?:^|[;{\s])(width|height|padding|margin|display|position)\s*:/m.test(block.replace(/outline-offset/g, "")), "no layout properties in the crimson block");
});
