// All state lives in this browser tab for this session only - nothing is
// persisted server-side or in local storage (matches the rest of the site:
// "we don't store your job description or resume after your session
// ends"). The resume file is held as a File object in memory until the
// person clicks "Prepare Me" - it's never uploaded anywhere until that one
// request.
let resumeFile = null;

const stepInput = document.getElementById("step-input");
const stepLoading = document.getElementById("step-loading");
const stepResults = document.getElementById("step-results");

const prepareForm = document.getElementById("prepare-form");
const prepareBtn = document.getElementById("prepare-btn");
const prepareError = document.getElementById("prepare-error");
const jobDescriptionInput = document.getElementById("job-description");

const resumeFileInput = document.getElementById("resume-file");
const resumeSelectedName = document.getElementById("resume-selected-name");

const jobDescriptionThinNotice = document.getElementById("job-description-thin-notice");
// Purely an advisory hint, not a validation gate - the server's own
// MIN_JOB_DESCRIPTION_CHARS (40, in main.py) is what actually blocks
// submission. This is a higher, deterministic threshold just for the
// non-blocking "this is pretty thin" notice: short enough that a real job
// posting is very unlikely to fall under it, long enough that it won't
// fire on ordinary complete postings.
const THIN_JOB_DESCRIPTION_CHARS = 150;

jobDescriptionInput.addEventListener("input", () => {
  const length = jobDescriptionInput.value.trim().length;
  jobDescriptionThinNotice.hidden = length === 0 || length >= THIN_JOB_DESCRIPTION_CHARS;
});

const PROCESSING_MESSAGES = [
  "Reading the job description...",
  "Identifying what this employer likely values...",
  "Drafting questions you may be asked...",
  "Thinking through questions you could ask them...",
  "Preparing your results...",
];

function showError(el, message) {
  el.textContent = message;
  el.hidden = false;
}

resumeFileInput.addEventListener("change", () => {
  resumeFile = resumeFileInput.files[0] || null;
  if (resumeFile) {
    resumeSelectedName.textContent = `Selected: ${resumeFile.name}`;
    resumeSelectedName.hidden = false;
  } else {
    resumeSelectedName.hidden = true;
  }
});

prepareForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  prepareError.hidden = true;

  const jobDescription = jobDescriptionInput.value.trim();
  if (!jobDescription) {
    showError(prepareError, "Please paste the job description.");
    return;
  }

  const formData = new FormData();
  formData.append("job_description", jobDescription);
  if (resumeFile) {
    formData.append("resume_file", resumeFile);
  }

  prepareBtn.disabled = true;
  stepInput.hidden = true;
  stepLoading.hidden = false;
  startProcessingState(stepLoading, PROCESSING_MESSAGES);

  try {
    const res = await fetch("/api/prepare", { method: "POST", body: formData });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || `Request failed (${res.status})`);
    }
    const data = await res.json();

    stopProcessingState(stepLoading);
    stepLoading.hidden = true;
    renderResults(data);
    stepResults.hidden = false;
  } catch (err) {
    stopProcessingState(stepLoading);
    stepLoading.hidden = true;
    stepInput.hidden = false;
    showError(prepareError, err.message || "Something went wrong. Please try again.");
  } finally {
    prepareBtn.disabled = false;
  }
});

const SIGNAL_LABELS = {
  job_description: "Job description signal:",
  resume: "Resume signal:",
};

function renderResults(data) {
  // Employer priorities
  const chipsRow = document.getElementById("priorities-chips");
  chipsRow.innerHTML = "";
  (data.employer_priorities || []).forEach((theme) => {
    const chip = document.createElement("span");
    chip.className = "theme-chip";
    chip.textContent = theme;
    chipsRow.appendChild(chip);
  });

  // Question groups
  const groupsContainer = document.getElementById("question-groups");
  groupsContainer.innerHTML = "";
  (data.question_groups || []).forEach((group) => {
    const groupWrap = document.createElement("div");
    groupWrap.className = "prepare-question-group";

    const heading = document.createElement("h4");
    heading.textContent = group.category;
    groupWrap.appendChild(heading);

    (group.questions || []).forEach((q) => {
      groupWrap.appendChild(buildQuestionCard(q));
    });

    groupsContainer.appendChild(groupWrap);
  });

  // Candidate questions
  fillList("candidate-questions-list", data.candidate_questions);

  // Prep tip
  document.getElementById("prep-tip").textContent = data.prep_tip || "";
}

function buildQuestionCard(q) {
  const card = document.createElement("div");
  card.className = "prepare-question-card";

  const questionP = document.createElement("p");
  questionP.className = "prepare-question-text";
  questionP.textContent = q.question;
  card.appendChild(questionP);

  if (q.why) {
    const whyP = document.createElement("p");
    whyP.className = "prepare-question-why";
    whyP.innerHTML = `<strong>Why they may ask:</strong> ${escapeHtml(q.why)}`;
    card.appendChild(whyP);
  }

  const signalLabel = SIGNAL_LABELS[q.source];
  if (signalLabel && q.signal) {
    const signalP = document.createElement("p");
    signalP.className = "prepare-question-signal";
    signalP.innerHTML = `<strong>${signalLabel}</strong> “${escapeHtml(q.signal)}”`;
    card.appendChild(signalP);
  }

  return card;
}

// Escapes quote characters too, not just <>&, so this helper stays safe
// even if a future call site interpolates into an attribute value (where a
// bare quote could otherwise break out of the attribute), not just text
// content between tags.
function escapeHtml(str) {
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function fillList(elementId, items) {
  const el = document.getElementById(elementId);
  el.innerHTML = "";
  (items || []).forEach((item) => {
    const li = document.createElement("li");
    li.textContent = item;
    el.appendChild(li);
  });
}

document.getElementById("start-over-btn").addEventListener("click", () => {
  stepResults.hidden = true;
  stepInput.hidden = false;
});
