// Career-Profile-driven job comparison: paste a job -> compare against the
// whole Career Profile -> gap interview (mirrors resumeReview.js's
// question-batch pattern, itself mirroring elevate.js) -> build a tailored
// resume from real profile evidence -> download via the existing
// /api/generate endpoint (unchanged). Relies on authedFetch()/escapeHtml()/
// makeTextField() from login.js/resumeReview.js and
// startProcessingState()/stopProcessingState() from loading.js, all loaded
// before this file.

const jobState = {
  jobDescription: "",
  categories: [],
  history: [],
  roundNumber: 1,
  discoveredFacts: [],
  matchReport: null,
  tailoredResumeData: null,
};
let currentJobQuestions = [];
const JOB_MAX_ROUNDS = 4;

const jobTargetEmpty = document.getElementById("job-target-empty");
const jobInputState = document.getElementById("job-input-state");
const jobLoadingState = document.getElementById("job-loading-state");
const jobMatchState = document.getElementById("job-match-state");
const jobQuestionsState = document.getElementById("job-questions-state");
const jobBuildFormState = document.getElementById("job-build-form-state");
const jobBuildLoadingState = document.getElementById("job-build-loading-state");
const jobBuildDoneState = document.getElementById("job-build-done-state");

function hideAllJobStates() {
  jobTargetEmpty.hidden = true;
  jobInputState.hidden = true;
  jobLoadingState.hidden = true;
  jobMatchState.hidden = true;
  jobQuestionsState.hidden = true;
  jobBuildFormState.hidden = true;
  jobBuildLoadingState.hidden = true;
  jobBuildDoneState.hidden = true;
}

document.getElementById("job-target-add-btn").addEventListener("click", () => {
  hideAllJobStates();
  jobInputState.hidden = false;
});

document.getElementById("job-cancel-btn").addEventListener("click", () => {
  hideAllJobStates();
  jobTargetEmpty.hidden = false;
});

document.getElementById("job-compare-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const errorEl = document.getElementById("job-compare-error");
  errorEl.hidden = true;

  const jobDescription = document.getElementById("job-description-input").value.trim();
  if (!jobDescription) return;
  jobState.jobDescription = jobDescription;

  hideAllJobStates();
  jobLoadingState.hidden = false;
  startProcessingState(jobLoadingState, [
    "Reading the job posting...",
    "Comparing it to your Career Profile...",
    "Identifying what's worth exploring...",
  ]);

  try {
    const res = await authedFetch("/api/career/job-compare", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ job_description: jobDescription }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || `Request failed (${res.status})`);
    }
    const data = await res.json();

    jobState.matchReport = data.match_report;
    jobState.categories = data.categories || [];
    jobState.history = [];
    jobState.roundNumber = 1;
    jobState.discoveredFacts = [];
    currentJobQuestions = data.questions || [];

    renderJobMatch(data.match_report);

    stopProcessingState(jobLoadingState);
    jobLoadingState.hidden = true;
    jobMatchState.hidden = false;
  } catch (err) {
    stopProcessingState(jobLoadingState);
    hideAllJobStates();
    jobInputState.hidden = false;
    errorEl.textContent = err.message || "Something went wrong. Please try again.";
    errorEl.hidden = false;
  }
});

function renderJobMatch(matchReport) {
  document.getElementById("job-match-level").textContent = matchReport.match_level;
  document.getElementById("job-match-rationale").textContent = matchReport.match_rationale;

  const strengthsList = document.getElementById("job-strengths-list");
  strengthsList.textContent = "";
  (matchReport.strengths || []).forEach((s) => {
    const li = document.createElement("li");
    li.textContent = s;
    strengthsList.appendChild(li);
  });

  const gapsList = document.getElementById("job-gaps-list");
  gapsList.textContent = "";
  const gaps = matchReport.required_qualification_gaps || [];
  if (gaps.length === 0) {
    const li = document.createElement("li");
    li.className = "hint";
    li.textContent = "Nothing stood out as unconfirmed against this posting.";
    gapsList.appendChild(li);
  } else {
    gaps.forEach((g) => {
      const li = document.createElement("li");
      li.textContent = g.requirement + " — " + g.explanation;
      gapsList.appendChild(li);
    });
  }
}

document.getElementById("job-start-interview-btn").addEventListener("click", () => {
  hideAllJobStates();
  if (currentJobQuestions.length) {
    renderJobQuestionsBatch(currentJobQuestions);
    jobQuestionsState.hidden = false;
  } else {
    showJobBuildForm();
  }
});

document.getElementById("job-skip-interview-btn").addEventListener("click", () => {
  hideAllJobStates();
  showJobBuildForm();
});

function renderJobQuestionsBatch(questions) {
  const container = document.getElementById("job-questions-list");
  container.innerHTML = "";

  questions.forEach((q) => {
    const card = document.createElement("div");
    card.className = "question-card";

    const p = document.createElement("p");
    p.textContent = q.question;
    card.appendChild(p);

    if (q.type === "detail") {
      const label = document.createElement("label");
      label.className = "field";
      const textarea = document.createElement("textarea");
      textarea.rows = 3;
      textarea.dataset.qid = q.id;
      textarea.placeholder = "Your answer, in your own words...";
      label.appendChild(textarea);
      card.appendChild(label);
    } else {
      const options = document.createElement("div");
      options.className = "question-options";
      options.innerHTML = `
        <label><input type="radio" name="${escapeHtml(q.id)}" value="yes" /> Yes</label>
        <label><input type="radio" name="${escapeHtml(q.id)}" value="no" /> No</label>
        <label><input type="radio" name="${escapeHtml(q.id)}" value="skip" checked /> Not sure / skip</label>
      `;
      card.appendChild(options);
    }

    container.appendChild(card);
  });
}

function collectJobAnswers() {
  return currentJobQuestions.map((q) => {
    let answer;
    if (q.type === "detail") {
      const textarea = document.querySelector(`#job-questions-list textarea[data-qid="${q.id}"]`);
      answer = textarea ? textarea.value.trim() : "";
    } else {
      const selected = document.querySelector(`#job-questions-list input[name="${q.id}"]:checked`);
      answer = selected ? selected.value : "skip";
    }
    return {
      id: q.id,
      category: q.category,
      question: q.question,
      type: q.type || "yes_no",
      follow_up_to: q.follow_up_to || null,
      answer,
    };
  });
}

async function submitJobAnswers(forceFinish) {
  const errorEl = document.getElementById("job-questions-error");
  errorEl.hidden = true;

  const answered = collectJobAnswers();
  jobState.history.push(...answered);

  jobQuestionsState.hidden = true;
  jobLoadingState.hidden = false;
  startProcessingState(jobLoadingState, [
    "Reviewing your answers...",
    "Deciding what to ask next...",
  ]);

  const effectiveForceFinish = forceFinish || jobState.roundNumber >= JOB_MAX_ROUNDS;

  try {
    const res = await authedFetch("/api/career/job-discover", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        resume_data: { job_description: jobState.jobDescription },
        categories: jobState.categories,
        history: jobState.history,
        force_finish: effectiveForceFinish,
        round_number: jobState.roundNumber,
      }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || `Request failed (${res.status})`);
    }
    const data = await res.json();

    stopProcessingState(jobLoadingState);
    jobLoadingState.hidden = true;

    if (data.stage === "confirm") {
      jobState.discoveredFacts = data.discovered_facts || [];
      showJobBuildForm();
    } else {
      currentJobQuestions = data.questions || [];
      jobState.roundNumber += 1;
      renderJobQuestionsBatch(currentJobQuestions);
      jobQuestionsState.hidden = false;
    }
  } catch (err) {
    stopProcessingState(jobLoadingState);
    jobQuestionsState.hidden = false;
    errorEl.textContent = err.message || "Something went wrong. Please try again.";
    errorEl.hidden = false;
  }
}

document.getElementById("job-questions-submit-btn").addEventListener("click", () => submitJobAnswers(false));
document.getElementById("job-questions-finish-btn").addEventListener("click", () => submitJobAnswers(true));

function showJobBuildForm() {
  hideAllJobStates();
  jobBuildFormState.hidden = false;
}

document.getElementById("job-build-btn").addEventListener("click", async () => {
  const errorEl = document.getElementById("job-build-error");
  errorEl.hidden = true;

  const name = document.getElementById("job-build-name").value.trim();
  const contact = document.getElementById("job-build-contact").value.trim();
  if (!name || !contact) {
    errorEl.textContent = "Please fill in both your name and a contact line.";
    errorEl.hidden = false;
    return;
  }

  hideAllJobStates();
  jobBuildLoadingState.hidden = false;
  startProcessingState(jobBuildLoadingState, [
    "Reviewing your Career Profile...",
    "Tailoring your resume to this role...",
    "Finalizing formatting...",
  ]);

  try {
    const res = await authedFetch("/api/career/job-build-resume", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        job_description: jobState.jobDescription,
        confirmed_facts: jobState.discoveredFacts,
        name,
        contact,
      }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || `Request failed (${res.status})`);
    }
    const data = await res.json();
    jobState.tailoredResumeData = data.resume_data;

    stopProcessingState(jobBuildLoadingState);
    jobBuildLoadingState.hidden = true;
    jobBuildDoneState.hidden = false;
  } catch (err) {
    stopProcessingState(jobBuildLoadingState);
    hideAllJobStates();
    jobBuildFormState.hidden = false;
    errorEl.textContent = err.message || "Something went wrong building your resume.";
    errorEl.hidden = false;
  }
});

document.getElementById("job-download-btn").addEventListener("click", async () => {
  if (!jobState.tailoredResumeData) return;
  try {
    const res = await authedFetch("/api/generate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ resume_data: jobState.tailoredResumeData, ats_mode: false }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || `Request failed (${res.status})`);
    }
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = (jobState.tailoredResumeData.name || "Resume").replace(/\s+/g, "_") + "_Tailored_Resume.docx";
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  } catch (err) {
    // The done-state has no dedicated error slot - a failed download here
    // is rare (the resume_data was already validated server-side to build
    // it) and retryable by clicking the same button again.
    alert(err.message || "Something went wrong downloading your resume. Please try again.");
  }
});

document.getElementById("job-start-over-btn").addEventListener("click", () => {
  jobState.jobDescription = "";
  jobState.categories = [];
  jobState.history = [];
  jobState.roundNumber = 1;
  jobState.discoveredFacts = [];
  jobState.matchReport = null;
  jobState.tailoredResumeData = null;
  document.getElementById("job-description-input").value = "";
  document.getElementById("job-build-name").value = "";
  document.getElementById("job-build-contact").value = "";
  hideAllJobStates();
  jobTargetEmpty.hidden = false;
});
