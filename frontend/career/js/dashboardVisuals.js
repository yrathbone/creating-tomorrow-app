// Career Profile status strip (Version 4.1): name, contact line, a six-step "career foundation" bar
// and a one-line evidence summary, all derived from data the dashboard has already loaded, plus the
// Edit Profile toggle for the resume-header form. Read-only apart from that form's own save (in
// profileBasics.js): it calls no API itself. It refreshes whenever the tiles refresh
// (updateDashboardSummary) or the resume header is shown (renderProfileBasicsForm), both defined
// in earlier scripts.

const CAREER_STEPS = [
  { key: "header", label: "your resume header", done: () => typeof profileBasics !== "undefined" && !!(profileBasics.display_name || profileBasics.contact_line) },
  { key: "roles", label: "a role", done: () => typeof allExperiences !== "undefined" && allExperiences.length > 0 },
  { key: "education", label: "your education", done: () => typeof allEducation !== "undefined" && allEducation.length > 0 },
  { key: "certifications", label: "a certification", done: () => typeof allCertifications !== "undefined" && allCertifications.length > 0 },
  { key: "skills", label: "your skills", done: () => typeof allSkills !== "undefined" && allSkills.length > 0 },
  { key: "languages", label: "your languages", done: () => typeof allLanguages !== "undefined" && allLanguages.length > 0 },
];

// Pure: which steps are done and what to say about them.
function careerProgressSummary(steps) {
  const done = steps.filter((s) => s.done);
  const next = steps.find((s) => !s.done);
  const text = done.length === steps.length
    ? "Complete"
    : done.length + " of " + steps.length + " started" + (next ? " \u00b7 next, add " + next.label : "");
  return { doneCount: done.length, total: steps.length, complete: done.length === steps.length, text };
}

// Pure: which of the bar's segments are lit. The bar fills from the left like a meter: 4 of 6 started lights
// the first four, whichever steps those happen to be (the text beside it still names the next step to take).
function careerProgressFill(doneCount, total) {
  return Array.from({ length: total }, (_, i) => i < doneCount);
}

// Pure: "3 roles · 2 education · 1 certification · 8 skills · 2 languages"
function careerEvidenceSummary(counts) {
  const parts = [
    [counts.roles, "role", "roles"],
    [counts.education, "education", "education"],
    [counts.certifications, "certification", "certifications"],
    [counts.skills, "skill", "skills"],
    [counts.languages, "language", "languages"],
  ].filter(([n]) => n > 0).map(([n, one, many]) => n + " " + (n === 1 ? one : many));
  return parts.length ? parts.join(" · ") : "No career evidence added yet";
}

// Pure: the letter shown in the little avatar ("" when there is no name yet).
function profileInitial(name) {
  const t = (name || "").trim();
  return t ? t.charAt(0).toUpperCase() : "";
}

function renderProfileStatus() {
  if (typeof document === "undefined") return;
  const nameEl = document.getElementById("cp-name");
  if (!nameEl) return;
  const name = typeof profileBasics !== "undefined" ? profileBasics.display_name : null;
  const contact = typeof profileBasics !== "undefined" ? profileBasics.contact_line : null;
  nameEl.textContent = name || "Add your name";
  nameEl.classList.toggle("is-empty", !name);
  const contactEl = document.getElementById("cp-contact");
  contactEl.textContent = contact || "Add a contact line";
  contactEl.classList.toggle("is-empty", !contact);
  document.getElementById("cp-avatar").textContent = profileInitial(name);
  const count = (v) => (typeof v !== "undefined" ? v.length : 0);
  document.getElementById("cp-evidence").textContent = careerEvidenceSummary({
    roles: count(typeof allExperiences !== "undefined" ? allExperiences : undefined),
    education: count(typeof allEducation !== "undefined" ? allEducation : undefined),
    certifications: count(typeof allCertifications !== "undefined" ? allCertifications : undefined),
    skills: count(typeof allSkills !== "undefined" ? allSkills : undefined),
    languages: count(typeof allLanguages !== "undefined" ? allLanguages : undefined),
  });
}

// Edit Profile: shows/hides the existing resume-header form (never permanently shown).
function setProfileEditorOpen(open) {
  const form = document.getElementById("profile-basics-form");
  const btn = document.getElementById("edit-profile-btn");
  if (!form || !btn) return;
  form.hidden = !open;
  btn.setAttribute("aria-expanded", open ? "true" : "false");
  if (open) {
    if (typeof renderProfileBasicsForm === "function") renderProfileBasicsForm();
    document.getElementById("profile-display-name").focus();
  }
}

function renderCareerProgress() {
  if (typeof document === "undefined") return;
  renderProfileStatus();
  const bar = document.getElementById("career-progress-bar");
  const sub = document.getElementById("career-progress-sub");
  if (!bar || !sub) return;
  const steps = CAREER_STEPS.map((s) => ({ key: s.key, label: s.label, done: !!s.done() }));
  const summary = careerProgressSummary(steps);
  const lit = careerProgressFill(summary.doneCount, steps.length);
  Array.from(bar.children).forEach((cell, i) => cell.classList.toggle("done", !!lit[i]));
  sub.textContent = summary.text;
  bar.setAttribute("aria-label", "Career foundation: " + summary.doneCount + " of " + summary.total + " steps started");
  const box = document.getElementById("career-progress");
  if (box) box.classList.toggle("complete", summary.complete);
}

// Refresh with the existing renderers (reassigning a global function declaration).
if (typeof updateDashboardSummary === "function") {
  const baseUpdateDashboardSummary = updateDashboardSummary;
  updateDashboardSummary = function () { baseUpdateDashboardSummary(); renderCareerProgress(); };
}
if (typeof renderProfileBasicsForm === "function") {
  const baseRenderProfileBasicsForm = renderProfileBasicsForm;
  renderProfileBasicsForm = function () { baseRenderProfileBasicsForm(); renderCareerProgress(); };
}

if (typeof document !== "undefined" && document.getElementById("edit-profile-btn")) {
  document.getElementById("edit-profile-btn").addEventListener("click", () => {
    setProfileEditorOpen(document.getElementById("profile-basics-form").hidden);
  });
  document.getElementById("profile-basics-cancel-btn").addEventListener("click", () => setProfileEditorOpen(false));
}
