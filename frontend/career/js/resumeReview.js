// Resume-driven Career Profile ingestion: upload -> extract roles -> the
// same discovery-interview loop Elevate uses (elevate.js's own pattern,
// mirrored here rather than reinvented) -> review/edit -> save. Relies on
// authedFetch()/currentAccessToken/loadExperiences() from login.js, and
// startProcessingState()/stopProcessingState() from loading.js - all
// loaded before this file in login.html.

const resumeState = {
  roles: [],
  categories: [],
  history: [],
  roundNumber: 1,
  discoveredFacts: [],
};
let currentResumeQuestions = [];
const RESUME_MAX_ROUNDS = 4;

function escapeHtml(str) {
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function showResumeError(el, message) {
  el.textContent = message;
  el.hidden = false;
}

function makeTextField(labelText, value, onInput) {
  const label = document.createElement("label");
  label.className = "field";
  const span = document.createElement("span");
  span.textContent = labelText;
  const input = document.createElement("input");
  input.type = "text";
  input.value = value || "";
  input.addEventListener("input", () => onInput(input.value));
  label.appendChild(span);
  label.appendChild(input);
  return label;
}

const resumeUploadForm = document.getElementById("resume-upload-form");
const resumeUploadBtn = document.getElementById("resume-upload-btn");
const resumeUploadError = document.getElementById("resume-upload-error");
const resumeUploadState = document.getElementById("resume-upload-state");
const resumeLoadingState = document.getElementById("resume-loading-state");
const resumeQuestionsState = document.getElementById("resume-questions-state");
const resumeReviewState = document.getElementById("resume-review-state");
const resumeDraftPrompt = document.getElementById("resume-draft-prompt");

let currentDraft = null;

// Persisted server-side (ResumeIngestionDraft), not just this tab's memory
// - checked every time the candidate opens the resume-upload area, so
// leaving mid-interview and coming back later (or from another device)
// doesn't lose their place.
async function checkForResumeDraft() {
  resumeDraftPrompt.hidden = true;
  resumeUploadState.hidden = true;
  resumeQuestionsState.hidden = true;
  resumeReviewState.hidden = true;

  try {
    const res = await authedFetch("/api/career/resume-draft");
    if (!res.ok) throw new Error();
    currentDraft = await res.json();

    if (currentDraft) {
      document.getElementById("draft-updated-at").textContent = currentDraft.updated_at
        ? new Date(currentDraft.updated_at).toLocaleString()
        : "earlier";
      resumeDraftPrompt.hidden = false;
    } else {
      resumeUploadState.hidden = false;
    }
  } catch (err) {
    // If the check itself fails, don't block the candidate - just fall
    // back to a fresh upload.
    resumeUploadState.hidden = false;
  }
}

function loadDraftIntoState(draft) {
  resumeState.roles = draft.roles || [];
  resumeState.categories = draft.categories || [];
  resumeState.history = draft.history || [];
  resumeState.discoveredFacts = draft.discovered_facts || [];
  resumeState.roundNumber = draft.round_number || 1;
  document.getElementById("resume-analysis-summary").textContent = draft.analysis_summary || "";

  if (draft.pending_questions && draft.pending_questions.length) {
    currentResumeQuestions = draft.pending_questions;
    renderResumeQuestionsBatch(currentResumeQuestions);
    resumeQuestionsState.hidden = false;
  } else {
    renderResumeReview();
    resumeReviewState.hidden = false;
  }
}

document.getElementById("resume-draft-continue-btn").addEventListener("click", () => {
  resumeDraftPrompt.hidden = true;
  if (currentDraft) loadDraftIntoState(currentDraft);
});

document.getElementById("resume-draft-discard-btn").addEventListener("click", async () => {
  await authedFetch("/api/career/resume-draft", { method: "DELETE" });
  currentDraft = null;
  resumeDraftPrompt.hidden = true;
  resumeUploadState.hidden = false;
});

resumeUploadForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  resumeUploadError.hidden = true;

  const fileInput = document.getElementById("resume-file");
  if (!fileInput.files.length) {
    showResumeError(resumeUploadError, "Please choose a resume file.");
    return;
  }

  const formData = new FormData();
  formData.append("resume_file", fileInput.files[0]);

  resumeUploadBtn.disabled = true;
  resumeUploadState.hidden = true;
  resumeLoadingState.hidden = false;
  startProcessingState(resumeLoadingState, [
    "Reading your resume...",
    "Identifying your roles...",
    "Preparing a few questions...",
  ]);

  try {
    const res = await authedFetch("/api/career/resume-start", { method: "POST", body: formData });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || `Request failed (${res.status})`);
    }
    const data = await res.json();

    resumeState.roles = data.roles || [];
    resumeState.categories = data.categories || [];
    resumeState.history = [];
    resumeState.roundNumber = 1;
    resumeState.discoveredFacts = [];
    currentResumeQuestions = data.questions || [];

    document.getElementById("resume-analysis-summary").textContent = data.analysis_summary || "";

    stopProcessingState(resumeLoadingState);
    resumeLoadingState.hidden = true;

    if (currentResumeQuestions.length) {
      renderResumeQuestionsBatch(currentResumeQuestions);
      resumeQuestionsState.hidden = false;
    } else {
      renderResumeReview();
      resumeReviewState.hidden = false;
    }
  } catch (err) {
    stopProcessingState(resumeLoadingState);
    resumeLoadingState.hidden = true;
    resumeUploadState.hidden = false;
    showResumeError(resumeUploadError, err.message || "Something went wrong. Please try again.");
  } finally {
    resumeUploadBtn.disabled = false;
  }
});

function renderResumeQuestionsBatch(questions) {
  const container = document.getElementById("resume-questions-list");
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

function collectResumeAnswers() {
  return currentResumeQuestions.map((q) => {
    let answer;
    if (q.type === "detail") {
      const textarea = document.querySelector(`#resume-questions-list textarea[data-qid="${q.id}"]`);
      answer = textarea ? textarea.value.trim() : "";
    } else {
      const selected = document.querySelector(`#resume-questions-list input[name="${q.id}"]:checked`);
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

async function submitResumeAnswers(forceFinish) {
  const questionsError = document.getElementById("resume-questions-error");
  questionsError.hidden = true;

  const answered = collectResumeAnswers();
  resumeState.history.push(...answered);

  resumeQuestionsState.hidden = true;
  resumeLoadingState.hidden = false;
  startProcessingState(resumeLoadingState, [
    "Reviewing your answers...",
    "Deciding what to ask next...",
  ]);

  const effectiveForceFinish = forceFinish || resumeState.roundNumber >= RESUME_MAX_ROUNDS;

  try {
    const res = await authedFetch("/api/career/resume-discover", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        resume_data: { roles: resumeState.roles },
        categories: resumeState.categories,
        history: resumeState.history,
        force_finish: effectiveForceFinish,
        round_number: resumeState.roundNumber,
      }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || `Request failed (${res.status})`);
    }
    const data = await res.json();

    stopProcessingState(resumeLoadingState);
    resumeLoadingState.hidden = true;

    if (data.stage === "confirm") {
      resumeState.discoveredFacts = data.discovered_facts || [];
      renderResumeReview();
      resumeReviewState.hidden = false;
    } else {
      currentResumeQuestions = data.questions || [];
      resumeState.roundNumber += 1;
      renderResumeQuestionsBatch(currentResumeQuestions);
      resumeQuestionsState.hidden = false;
    }
  } catch (err) {
    stopProcessingState(resumeLoadingState);
    resumeLoadingState.hidden = true;
    resumeQuestionsState.hidden = false;
    showResumeError(questionsError, err.message || "Something went wrong. Please try again.");
  }
}

document.getElementById("resume-questions-submit-btn").addEventListener("click", () => submitResumeAnswers(false));
document.getElementById("resume-questions-finish-btn").addEventListener("click", () => submitResumeAnswers(true));

function renderResumeReview() {
  const rolesContainer = document.getElementById("resume-roles-list");
  rolesContainer.innerHTML = "";

  resumeState.roles.forEach((role, idx) => {
    const card = document.createElement("div");
    card.className = "entry-summary-card";

    const header = document.createElement("div");
    header.className = "entry-summary-header";
    const titleSpan = document.createElement("span");
    titleSpan.className = "hint";
    titleSpan.textContent = "Role " + (idx + 1);
    const removeBtn = document.createElement("button");
    removeBtn.type = "button";
    removeBtn.className = "entry-remove-btn";
    removeBtn.textContent = "Remove";
    removeBtn.addEventListener("click", () => {
      resumeState.roles.splice(idx, 1);
      renderResumeReview();
    });
    header.appendChild(titleSpan);
    header.appendChild(removeBtn);
    card.appendChild(header);

    card.appendChild(makeTextField("Title", role.title, (v) => { role.title = v; }));
    card.appendChild(makeTextField("Organization", role.organization, (v) => { role.organization = v; }));

    const datesRow = document.createElement("div");
    datesRow.className = "field-row";
    datesRow.appendChild(makeTextField("Start date", role.start_date, (v) => { role.start_date = v; }));
    datesRow.appendChild(makeTextField("End date", role.end_date, (v) => { role.end_date = v; }));
    card.appendChild(datesRow);

    const bulletsField = document.createElement("label");
    bulletsField.className = "field";
    const bulletsSpan = document.createElement("span");
    bulletsSpan.textContent = "What you did";
    const bulletsTextarea = document.createElement("textarea");
    bulletsTextarea.rows = 4;
    bulletsTextarea.value = (role.bullets || []).join("\n");
    bulletsTextarea.addEventListener("input", () => {
      role.bullets = bulletsTextarea.value.split("\n").map((b) => b.trim()).filter(Boolean);
    });
    bulletsField.appendChild(bulletsSpan);
    bulletsField.appendChild(bulletsTextarea);
    card.appendChild(bulletsField);

    rolesContainer.appendChild(card);
  });

  renderResumeFacts();
}

function renderResumeFacts() {
  const factsContainer = document.getElementById("resume-facts-list");
  factsContainer.innerHTML = "";
  document.getElementById("resume-facts-block").hidden = resumeState.discoveredFacts.length === 0;

  resumeState.discoveredFacts.forEach((fact, idx) => {
    const card = document.createElement("div");
    card.className = "entry-summary-card";

    const header = document.createElement("div");
    header.className = "entry-summary-header";
    const categorySpan = document.createElement("span");
    categorySpan.className = "hint";
    categorySpan.textContent = fact.category || "";
    const removeBtn = document.createElement("button");
    removeBtn.type = "button";
    removeBtn.className = "entry-remove-btn";
    removeBtn.textContent = "Remove";
    removeBtn.addEventListener("click", () => {
      resumeState.discoveredFacts.splice(idx, 1);
      renderResumeFacts();
    });
    header.appendChild(categorySpan);
    header.appendChild(removeBtn);
    card.appendChild(header);

    const textareaLabel = document.createElement("label");
    textareaLabel.className = "field";
    const textarea = document.createElement("textarea");
    textarea.rows = 2;
    textarea.value = fact.bullet_text || "";
    textarea.addEventListener("input", () => { fact.bullet_text = textarea.value; });
    textareaLabel.appendChild(textarea);
    card.appendChild(textareaLabel);

    const selectLabel = document.createElement("label");
    selectLabel.className = "field";
    const selectSpan = document.createElement("span");
    selectSpan.textContent = "Which role does this belong to?";
    const select = document.createElement("select");
    resumeState.roles.forEach((role, roleIdx) => {
      const option = document.createElement("option");
      option.value = String(roleIdx);
      option.textContent = (role.title || "Role " + (roleIdx + 1)) + (role.organization ? " — " + role.organization : "");
      select.appendChild(option);
    });
    if (fact.roleIndex !== undefined) select.value = String(fact.roleIndex);
    fact.roleIndex = select.value ? Number(select.value) : 0;
    select.addEventListener("change", () => { fact.roleIndex = Number(select.value); });
    selectLabel.appendChild(selectSpan);
    selectLabel.appendChild(select);
    card.appendChild(selectLabel);

    factsContainer.appendChild(card);
  });
}

document.getElementById("resume-save-btn").addEventListener("click", async () => {
  const saveError = document.getElementById("resume-save-error");
  saveError.hidden = true;
  const saveBtn = document.getElementById("resume-save-btn");
  saveBtn.disabled = true;

  try {
    const res = await authedFetch("/api/career/resume-save", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        roles: resumeState.roles,
        confirmed_facts: resumeState.discoveredFacts.map((f) => ({
          bullet_text: f.bullet_text,
          role_index: f.roleIndex,
        })),
      }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || `Request failed (${res.status})`);
    }
    const savedRoles = await res.json();

    resumeReviewState.hidden = true;
    resumeState.roles = [];
    resumeState.discoveredFacts = [];
    resumeState.history = [];
    resumeState.roundNumber = 1;
    currentDraft = null;

    document.getElementById("resume-save-summary-text").textContent =
      "Saved " + savedRoles.length + " role" + (savedRoles.length === 1 ? "" : "s") + " to your Career Profile.";
    document.getElementById("resume-save-summary").hidden = false;

    await loadExperiences();
  } catch (err) {
    showResumeError(saveError, err.message || "Something went wrong saving your roles.");
  } finally {
    saveBtn.disabled = false;
  }
});

document.getElementById("resume-save-continue-btn").addEventListener("click", () => {
  document.getElementById("resume-save-summary").hidden = true;
  resumeUploadForm.reset();
  resumeUploadState.hidden = false;
});
