// All state lives in the browser tab for this session only - nothing is
// persisted server-side between requests, on purpose (privacy: we never
// want a resume + job posting sitting in a database).
let resumeData = null;
let reflectiveQuestions = [];
let currentMode = null; // "build", "analyze", or "upgrade"

const stepMode = document.getElementById("step-mode");
const stepUpload = document.getElementById("step-upload");
const stepLoading = document.getElementById("step-loading");
const stepResults = document.getElementById("step-results");
const stepQuestions = document.getElementById("step-questions");

const uploadHeading = document.getElementById("upload-heading");
const uploadHint = document.getElementById("upload-hint");
const jobPostingField = document.getElementById("job-posting-field");
const jobPostingInput = document.getElementById("job-posting");
const loadingText = document.getElementById("loading-text");

const analyzeForm = document.getElementById("analyze-form");
const analyzeBtn = document.getElementById("analyze-btn");
const analyzeError = document.getElementById("analyze-error");

const resultsHeading = document.getElementById("results-heading");
const matchModeResults = document.getElementById("match-mode-results");
const buildModeResults = document.getElementById("build-mode-results");
const upgradeModeResults = document.getElementById("upgrade-mode-results");

const questionsHeading = document.getElementById("questions-heading");
const questionsHint = document.getElementById("questions-hint");

const generateBtn = document.getElementById("generate-btn");
const generateError = document.getElementById("generate-error");

const MODE_CONFIG = {
  build: {
    endpoint: "/api/build",
    uploadHeading: "1. Waypoint: Tell us about you",
    uploadHint: "Upload your current resume. We'll research what your role typically involves today and help you rebuild it honestly — no job posting required.",
    loadingText: 'Reading your resume and researching your role — this takes about <span class="loading-emphasis">30-60 seconds</span>. Please don\'t refresh or close this page while we work.',
    needsJobPosting: false,
    resultsHeading: "2. Your honest report",
  },
  analyze: {
    endpoint: "/api/analyze",
    uploadHeading: "1. Landing Spot: Tell us about the role",
    uploadHint: "Upload your current resume and paste in the job posting you're aiming for. We'll compare them honestly — not just by counting keywords.",
    loadingText: 'Reading your resume and comparing it to the posting — this takes about <span class="loading-emphasis">30-60 seconds</span>. Please don\'t refresh or close this page while we work.',
    needsJobPosting: true,
    resultsHeading: "2. Your honest report",
  },
  upgrade: {
    endpoint: "/api/upgrade",
    uploadHeading: "1. Summit: Tell us about you",
    uploadHint: "Upload your current resume. We'll rewrite it in polished, professional language — no job posting needed, and we won't add anything that isn't already true on your resume.",
    loadingText: 'Reading your resume and rewriting it in sharper language — this takes about <span class="loading-emphasis">30-60 seconds</span>. Please don\'t refresh or close this page while we work.',
    needsJobPosting: false,
    resultsHeading: "2. Your rewritten resume",
  },
};

document.querySelectorAll(".mode-btn").forEach((btn) => {
  btn.addEventListener("click", () => selectMode(btn.dataset.mode));
});

function selectMode(mode) {
  currentMode = mode;
  const config = MODE_CONFIG[mode];

  uploadHeading.textContent = config.uploadHeading;
  uploadHint.textContent = config.uploadHint;
  jobPostingField.hidden = !config.needsJobPosting;
  jobPostingInput.required = config.needsJobPosting;
  loadingText.innerHTML = config.loadingText;
  resultsHeading.textContent = config.resultsHeading;

  stepMode.hidden = true;
  stepUpload.hidden = false;
}

analyzeForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  analyzeError.hidden = true;

  const config = MODE_CONFIG[currentMode];
  const fileInput = document.getElementById("resume-file");
  const jobPosting = jobPostingInput.value.trim();

  if (!fileInput.files.length) {
    showError(analyzeError, "Please upload a resume.");
    return;
  }
  if (config.needsJobPosting && !jobPosting) {
    showError(analyzeError, "Please paste the job posting.");
    return;
  }

  const formData = new FormData();
  formData.append("resume_file", fileInput.files[0]);
  if (config.needsJobPosting) {
    formData.append("job_posting", jobPosting);
  }

  analyzeBtn.disabled = true;
  stepUpload.hidden = true;
  stepLoading.hidden = false;

  try {
    const res = await fetch(config.endpoint, { method: "POST", body: formData });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || `Request failed (${res.status})`);
    }
    const data = await res.json();
    resumeData = data.resume_data;
    reflectiveQuestions = data.reflective_questions || [];

    matchModeResults.hidden = currentMode !== "analyze";
    buildModeResults.hidden = currentMode !== "build";
    upgradeModeResults.hidden = currentMode !== "upgrade";

    if (currentMode === "analyze") {
      renderMatchReport(data.match_report);
    } else if (currentMode === "build") {
      document.getElementById("role-research-summary").textContent = data.role_research_summary || "";
    } else if (currentMode === "upgrade") {
      document.getElementById("upgrade-summary-preview").textContent = resumeData.summary || "";
    }

    renderQuestions(reflectiveQuestions);
    if (reflectiveQuestions.length) {
      questionsHeading.textContent = "3. Be honest with yourself";
      questionsHint.hidden = false;
    } else {
      questionsHeading.textContent = "3. Review & download";
      questionsHint.hidden = true;
    }

    stepLoading.hidden = true;
    stepResults.hidden = false;
    stepQuestions.hidden = false;
  } catch (err) {
    stepLoading.hidden = true;
    stepUpload.hidden = false;
    showError(analyzeError, err.message || "Something went wrong. Please try again.");
  } finally {
    analyzeBtn.disabled = false;
  }
});

function renderMatchReport(report) {
  document.getElementById("grade-badge").textContent = "Grade: " + report.grade;
  document.getElementById("grade-rationale").textContent = report.grade_rationale || "";

  fillList("strengths-list", report.strengths, (s) => s);

  fillList("gaps-list", report.required_qualification_gaps, (g) => {
    return `<span class="gap-status">[${g.status}]</span>${g.requirement} — ${g.explanation}`;
  });

  const flags = report.same_word_different_job_flags || [];
  const flagsBlock = document.getElementById("flags-block");
  if (flags.length) {
    flagsBlock.hidden = false;
    fillList("flags-list", flags, (f) => {
      return `<span class="flag-term">"${f.term}"</span> — on your resume: ${f.resume_meaning}. In the posting: ${f.posting_meaning}. ${f.why_it_matters}`;
    });
  } else {
    flagsBlock.hidden = true;
  }

  fillList("growth-list", report.growth_suggestions, (s) => s);

  document.getElementById("fit-note").textContent = report.note_on_better_fit_roles || "";
}

function fillList(elementId, items, formatter) {
  const el = document.getElementById(elementId);
  el.innerHTML = "";
  (items || []).forEach((item) => {
    const li = document.createElement("li");
    li.innerHTML = formatter(item);
    el.appendChild(li);
  });
}

function renderQuestions(questions) {
  const container = document.getElementById("questions-list");
  container.innerHTML = "";

  questions.forEach((q) => {
    const card = document.createElement("div");
    card.className = "question-card";

    const p = document.createElement("p");
    p.textContent = q.question;
    card.appendChild(p);

    const options = document.createElement("div");
    options.className = "question-options";
    options.innerHTML = `
      <label><input type="radio" name="${q.id}" value="yes" /> Yes</label>
      <label><input type="radio" name="${q.id}" value="no" /> No</label>
      <label><input type="radio" name="${q.id}" value="skip" checked /> Not sure / skip</label>
    `;
    card.appendChild(options);
    container.appendChild(card);
  });
}

generateBtn.addEventListener("click", async () => {
  generateError.hidden = true;

  // Apply confirmed ("yes") answers to a copy of the resume data.
  const finalData = JSON.parse(JSON.stringify(resumeData));

  reflectiveQuestions.forEach((q) => {
    const selected = document.querySelector(`input[name="${q.id}"]:checked`);
    if (!selected || selected.value !== "yes") return;

    const addition = q.add_if_yes;
    if (!addition) return;

    if (addition.type === "skill") {
      finalData.skills.push(addition.text);
    } else if (addition.type === "bullet") {
      const idx = addition.experience_index || 0;
      if (finalData.experience[idx]) {
        finalData.experience[idx].bullets.push(addition.text);
      }
    }
  });

  const atsMode = document.getElementById("ats-mode").checked;

  generateBtn.disabled = true;
  try {
    const res = await fetch("/api/generate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ resume_data: finalData, ats_mode: atsMode }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || `Request failed (${res.status})`);
    }
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = (finalData.name || "Resume").replace(/\s+/g, "_") + "_Resume.docx";
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);

    const generateSuccess = document.getElementById("generate-success");
    generateSuccess.textContent = "Your resume is downloading. Need another version (like switching ATS mode)? Generate again below. Otherwise, you're all set.";
    generateSuccess.hidden = false;
    document.getElementById("finish-btn").hidden = false;
  } catch (err) {
    showError(generateError, err.message || "Something went wrong generating your resume.");
  } finally {
    generateBtn.disabled = false;
  }
});

document.getElementById("finish-btn").addEventListener("click", () => {
  window.location.href = "index.html";
});

function showError(el, message) {
  el.textContent = message;
  el.hidden = false;
}
