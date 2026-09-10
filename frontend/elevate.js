// All state lives in this browser tab for this session only - nothing is
// persisted server-side or in local storage (matches the rest of the site:
// "we don't store your information after your session ends").
const state = {
  resumeData: null, // restructured facts, from /api/elevate-start
  categories: [],
  history: [], // { id, category, question, type, answer, follow_up_to }
  roundNumber: 1,
  discoveredFacts: [], // { id, category, bullet_text }
  finalResumeData: null,
};

let currentQuestions = []; // the batch currently on screen, awaiting answers

const MAX_ROUNDS = 4; // hard cap on discovery rounds regardless of what the model wants - keeps cost/time bounded

function goToStep(stepName) {
  document.querySelectorAll(".wizard-step").forEach((el) => (el.hidden = true));
  document.getElementById(`step-${stepName}`).hidden = false;

  document.querySelectorAll(".wizard-step-label").forEach((el) => {
    el.classList.toggle("active", el.dataset.step === stepName);
  });
}

function showError(el, message) {
  el.textContent = message;
  el.hidden = false;
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

// --- Step 1: Upload -----------------------------------------------------
const uploadForm = document.getElementById("upload-form");
const uploadBtn = document.getElementById("upload-btn");
const uploadError = document.getElementById("upload-error");
const uploadLoading = document.getElementById("upload-loading");

uploadForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  uploadError.hidden = true;

  const fileInput = document.getElementById("resume-file");
  if (!fileInput.files.length) {
    showError(uploadError, "Please upload a resume.");
    return;
  }

  const formData = new FormData();
  formData.append("resume_file", fileInput.files[0]);

  uploadBtn.disabled = true;
  uploadForm.hidden = true;
  uploadLoading.hidden = false;

  try {
    const res = await fetch("/api/elevate-start", { method: "POST", body: formData });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || `Request failed (${res.status})`);
    }
    const data = await res.json();

    state.resumeData = data.resume_data;
    state.categories = data.categories || [];
    currentQuestions = data.questions || [];

    document.getElementById("analysis-summary").textContent = data.analysis_summary || "";

    uploadLoading.hidden = true;
    goToStep("analysis");
  } catch (err) {
    uploadLoading.hidden = true;
    uploadForm.hidden = false;
    showError(uploadError, err.message || "Something went wrong. Please try again.");
  } finally {
    uploadBtn.disabled = false;
  }
});

// --- Step 2: Analysis -----------------------------------------------------
document.getElementById("analysis-continue-btn").addEventListener("click", () => {
  renderQuestionsBatch(currentQuestions);
  goToStep("questions");
});

// --- Step 3: Discovery loop ------------------------------------------------
const questionsLoading = document.getElementById("questions-loading");
const questionsFormWrap = document.getElementById("questions-form-wrap");
const questionsError = document.getElementById("questions-error");

function renderQuestionsBatch(questions) {
  const container = document.getElementById("discovery-questions-list");
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
        <label><input type="radio" name="${q.id}" value="yes" /> Yes</label>
        <label><input type="radio" name="${q.id}" value="no" /> No</label>
        <label><input type="radio" name="${q.id}" value="skip" checked /> Not sure / skip</label>
      `;
      card.appendChild(options);
    }

    container.appendChild(card);
  });
}

function collectAnswers() {
  return currentQuestions.map((q) => {
    let answer;
    if (q.type === "detail") {
      const textarea = document.querySelector(`textarea[data-qid="${q.id}"]`);
      answer = textarea ? textarea.value.trim() : "";
    } else {
      const selected = document.querySelector(`input[name="${q.id}"]:checked`);
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

async function submitAnswers(forceFinish) {
  questionsError.hidden = true;

  const answered = collectAnswers();
  state.history.push(...answered);

  questionsFormWrap.hidden = true;
  questionsLoading.hidden = false;

  const effectiveForceFinish = forceFinish || state.roundNumber >= MAX_ROUNDS;

  try {
    const res = await fetch("/api/elevate-discover", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        resume_data: state.resumeData,
        categories: state.categories,
        history: state.history,
        force_finish: effectiveForceFinish,
        round_number: state.roundNumber,
      }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || `Request failed (${res.status})`);
    }
    const data = await res.json();

    if (data.stage === "confirm") {
      state.discoveredFacts = data.discovered_facts || [];
      renderDiscoveredFacts();
      questionsLoading.hidden = true;
      goToStep("confirm");
    } else {
      currentQuestions = data.questions || [];
      state.roundNumber += 1;
      renderQuestionsBatch(currentQuestions);
      questionsLoading.hidden = true;
      questionsFormWrap.hidden = false;
    }
  } catch (err) {
    questionsLoading.hidden = true;
    questionsFormWrap.hidden = false;
    showError(questionsError, err.message || "Something went wrong. Please try again.");
  }
}

document.getElementById("questions-submit-btn").addEventListener("click", () => submitAnswers(false));
document.getElementById("questions-finish-btn").addEventListener("click", () => submitAnswers(true));

// --- Step 4: Confirm discovered facts ---------------------------------
function renderDiscoveredFacts() {
  const el = document.getElementById("discovered-facts-list");
  el.innerHTML = "";
  document.getElementById("confirm-empty-hint").hidden = state.discoveredFacts.length !== 0;

  state.discoveredFacts.forEach((fact, idx) => {
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
    removeBtn.dataset.idx = idx;
    removeBtn.textContent = "Remove";
    header.appendChild(categorySpan);
    header.appendChild(removeBtn);
    card.appendChild(header);

    const label = document.createElement("label");
    label.className = "field";
    const textarea = document.createElement("textarea");
    textarea.rows = 2;
    textarea.dataset.idx = idx;
    textarea.value = fact.bullet_text || "";
    label.appendChild(textarea);
    card.appendChild(label);

    el.appendChild(card);
  });

  el.querySelectorAll(".entry-remove-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      state.discoveredFacts.splice(Number(btn.dataset.idx), 1);
      renderDiscoveredFacts();
    });
  });
  el.querySelectorAll("textarea").forEach((ta) => {
    ta.addEventListener("input", () => {
      state.discoveredFacts[Number(ta.dataset.idx)].bullet_text = ta.value;
    });
  });
}

document.getElementById("confirm-continue-btn").addEventListener("click", async () => {
  goToStep("results");
  await runFinalize();
});

// --- Step 5: Results ------------------------------------------------------
async function runFinalize() {
  const resultsLoading = document.getElementById("results-loading");
  const resultsContent = document.getElementById("results-content");
  resultsLoading.hidden = false;
  resultsContent.hidden = true;

  try {
    const res = await fetch("/api/elevate-finalize", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        resume_data: state.resumeData,
        confirmed_facts: state.discoveredFacts,
      }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || `Request failed (${res.status})`);
    }
    const data = await res.json();

    state.finalResumeData = data.resume_data;

    const uncoveredBlock = document.getElementById("uncovered-block");
    if (data.uncovered && data.uncovered.length) {
      uncoveredBlock.hidden = false;
      fillList("uncovered-list", data.uncovered);
    } else {
      uncoveredBlock.hidden = true;
    }
    fillList("changes-list", data.changes);
    fillList("verify-list", data.verify);

    resultsLoading.hidden = true;
    resultsContent.hidden = false;
  } catch (err) {
    resultsLoading.hidden = true;
    showError(document.getElementById("generate-error"), err.message || "Something went wrong building your resume. Please try again.");
    document.getElementById("results-content").hidden = false;
  }
}

document.getElementById("generate-btn").addEventListener("click", async () => {
  const generateError = document.getElementById("generate-error");
  generateError.hidden = true;
  if (!state.finalResumeData) return;

  const resumeData = { ...state.finalResumeData, skills_heading: "CORE EXPERTISE" };
  const atsMode = document.getElementById("ats-mode").checked;
  const generateBtn = document.getElementById("generate-btn");
  generateBtn.disabled = true;

  try {
    const res = await fetch("/api/generate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ resume_data: resumeData, ats_mode: atsMode }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || `Request failed (${res.status})`);
    }
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = (resumeData.name || "Resume").replace(/\s+/g, "_") + "_Elevate_Resume.docx";
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);

    const generateSuccess = document.getElementById("generate-success");
    generateSuccess.textContent = "Your elevated resume is downloading. Need another version (like switching ATS mode)? Download again above. Otherwise, you're all set.";
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
