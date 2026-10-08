// "Your next step": one card at the top of the dashboard that names the single most useful thing to do
// right now, instead of every tile competing for attention. Read-only: it calls no API. It looks at data the
// dashboard has already loaded (roles, skills, scans, resumes, applications) and walks a short ladder; the
// first rung that applies wins. Clicking the button just triggers the control that already does the job
// (the same button or tile the person could have clicked themselves), so no new flow exists here.
// Refreshes whenever the tiles refresh (updateDashboardSummary, from login.js) and stays hidden until
// showProfileStep() has finished loading everything, so it never gives advice from half-loaded data.

const STALE_APPLICATION_DAYS = 14;

// Pure: facts -> { key, title, text, button, targets | href } or null (say nothing rather than guess).
//   f.roles / f.education / f.skills   counts
//   f.hasHeader                        a saved name or contact line
//   f.scans                            allScanHistory entries ({ id, scan_type, job_title })
//   f.resumes                          allResumeVersions entries ({ scan_history_id })
//   f.applications                     allApplications entries ({ status, applied_on }) or null if unavailable
//   f.today                            Date.now() (injectable for tests)
function chooseNextStep(f) {
  if (!f || !f.ready) return null;
  const tile = (key) => ['.stat-card[data-panel="' + key + '"]'];

  if (!f.roles) {
    return { key: "add-role", title: "Add your most recent role",
      text: "Everything here is built from your real experience. Upload your resume and we'll pull your roles in for you to check, or add one by hand.",
      button: "Upload My Resume", targets: ["#upload-resume-btn"] };
  }
  if (!f.skills) {
    return { key: "add-skills", title: "Add your skills",
      text: "Skills are the keywords employers look for. Add the ones you really have, or run a skill scan to find ones hiding in your roles.",
      button: "Add my skills", targets: tile("skills") };
  }
  if (!f.hasHeader) {
    return { key: "add-header", title: "Add your name and contact line",
      text: "Saved once, then filled in for you on every resume you build.",
      button: "Add them now", targets: ["#edit-profile-btn"] };
  }
  if (!f.education) {
    return { key: "add-education", title: "Add your education",
      text: "Schools, degrees and training, even if unfinished. Most resumes need this section.",
      button: "Add my education", targets: tile("education") };
  }

  const resumes = f.resumes || [];
  const scans = (f.scans || []).filter((s) => s.scan_type === "job_comparison");
  const tailored = resumes.filter((r) => r.scan_history_id);
  if (!resumes.length) {
    return { key: "first-resume", title: "Build your first resume",
      text: "Your Career Profile is ready. Turn it into a polished, honest resume in a couple of minutes.",
      button: "Build a General Resume", targets: ["#general-resume-hero-btn"] };
  }
  if (!scans.length) {
    return { key: "compare-job", title: "Compare a job you're interested in",
      text: "Paste a job posting and we'll show how your real experience lines up, and what you may be leaving out.",
      button: "Add a Job", targets: ["#job-target-add-btn"] };
  }
  const built = new Set(tailored.map((r) => r.scan_history_id));
  const unfinished = scans.find((s) => !built.has(s.id));
  if (unfinished) {
    return { key: "finish-resume", title: unfinished.job_title ? "Finish your resume for " + unfinished.job_title : "Finish your tailored resume",
      text: "You compared this job but haven't built a resume for it yet. Pick up where you left off.",
      button: "Continue", targets: ["#job-resume-last-btn"] };
  }

  const apps = f.applications;
  if (apps) {
    const today = f.today || Date.now();
    const days = (a) => {
      const then = new Date((a.applied_on || "") + "T00:00:00");
      return isNaN(then) ? null : Math.floor((today - then.getTime()) / 86400000);
    };
    const interviews = apps.filter((a) => a.status === "interview");
    if (interviews.length) {
      return { key: "prepare-interview", title: interviews.length === 1 ? "You have an interview: get ready" : "You have " + interviews.length + " interviews: get ready",
        text: "Practice the questions you're likely to hear, built from your own experience.",
        button: "Prepare for it", href: "../prepare.html" };
    }
    const waiting = apps.filter((a) => a.status === "applied" && days(a) !== null && days(a) >= STALE_APPLICATION_DAYS);
    if (waiting.length) {
      return { key: "check-applications", title: waiting.length === 1 ? "Check on an application" : "Check on " + waiting.length + " applications",
        text: "It's been " + STALE_APPLICATION_DAYS + "+ days. Update the status, or follow up if you haven't heard back.",
        button: "Open my applications", targets: tile("applications") };
    }
    if (!apps.length) {
      return { key: "track-application", title: "Applied for a job? Track it",
        text: "Add it to your tracker so you can see where every application stands and when to follow up.",
        button: "Open my applications", targets: tile("applications") };
    }
  }

  return { key: "keep-going", title: "Compare another job",
    text: "Each job you compare shows more of your real experience to add to your profile.",
    button: "Add a Job", targets: ["#job-target-add-btn"] };
}

// Gathers the facts from the dashboard's own globals (all declared by earlier scripts).
let nextStepReady = false;
function nextStepFacts() {
  const len = (v) => (typeof v !== "undefined" && v ? v.length : 0);
  return {
    ready: nextStepReady && typeof scansLoaded !== "undefined" && scansLoaded && typeof resumesLoaded !== "undefined" && resumesLoaded,
    roles: len(typeof allExperiences !== "undefined" ? allExperiences : undefined),
    education: len(typeof allEducation !== "undefined" ? allEducation : undefined),
    skills: len(typeof allSkills !== "undefined" ? allSkills : undefined),
    hasHeader: typeof profileBasics !== "undefined" && !!(profileBasics.display_name || profileBasics.contact_line),
    scans: typeof allScanHistory !== "undefined" ? allScanHistory : [],
    resumes: typeof allResumeVersions !== "undefined" ? allResumeVersions : [],
    applications: typeof applicationsUnavailable !== "undefined" && applicationsUnavailable ? null
      : (typeof allApplications !== "undefined" ? allApplications : null),
    today: Date.now(),
  };
}

// Clicks the first target that exists and is visible; for a tile also brings its opened list into view.
function runNextStep(step) {
  if (step.href) { window.location.href = step.href; return; }
  for (const selector of step.targets || []) {
    const el = document.querySelector(selector);
    if (!el || el.hidden) continue;
    // a tile toggles its list, so don't close one that is already open
    if (!(el.classList && el.classList.contains("active"))) el.click();
    const panelKey = el.dataset && el.dataset.panel;
    const panel = panelKey ? document.getElementById("panel-" + panelKey) : null;
    (panel && !panel.hidden ? panel : el).scrollIntoView({ behavior: "smooth", block: "center" });
    return;
  }
}

let nextStepCurrent = null;
function renderNextStep() {
  if (typeof document === "undefined") return;
  const box = document.getElementById("next-step");
  if (!box) return;
  const step = chooseNextStep(nextStepFacts());
  nextStepCurrent = step;
  box.hidden = !step;
  if (!step) return;
  box.dataset.step = step.key;
  document.getElementById("next-step-title").textContent = step.title;
  document.getElementById("next-step-text").textContent = step.text;
  document.getElementById("next-step-btn").textContent = step.button + (step.href ? " →" : "");
}

function markNextStepReady() {
  nextStepReady = true;
  renderNextStep();
}

if (typeof updateDashboardSummary === "function") {
  const baseUpdateDashboardSummaryForNextStep = updateDashboardSummary;
  updateDashboardSummary = function () { baseUpdateDashboardSummaryForNextStep(); renderNextStep(); };
}
if (typeof document !== "undefined" && document.getElementById("next-step-btn")) {
  document.getElementById("next-step-btn").addEventListener("click", () => { if (nextStepCurrent) runNextStep(nextStepCurrent); });
}
