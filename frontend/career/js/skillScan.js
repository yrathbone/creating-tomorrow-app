// Scans the whole Career Profile against what's typical for the kinds of
// roles it represents (not tied to one job posting or one upload) and
// interviews on anything that looks like a real blind spot. Reuses the
// existing /api/career/job-discover route for the interview loop -
// discover() doesn't care what triggered it. Relies on authedFetch()/
// escapeHtml()/allExperiences/loadExperiences() from login.js and
// startProcessingState()/stopProcessingState() from loading.js.

const skillScanState = {
  categories: [],
  history: [],
  roundNumber: 1,
  discoveredFacts: [],
};
let currentSkillScanQuestions = [];
const SKILL_SCAN_MAX_ROUNDS = 4;

const skillScanStart = document.getElementById("skill-scan-start");
const skillScanLoading = document.getElementById("skill-scan-loading");
const skillScanQuestions = document.getElementById("skill-scan-questions");
const skillScanComplete = document.getElementById("skill-scan-complete");
const skillScanReview = document.getElementById("skill-scan-review");

function hideAllSkillScanStates() {
  skillScanStart.hidden = true;
  skillScanLoading.hidden = true;
  skillScanQuestions.hidden = true;
  skillScanReview.hidden = true;
  skillScanComplete.hidden = true;
}

document.getElementById("skill-scan-btn").addEventListener("click", async () => {
  hideAllSkillScanStates();
  skillScanLoading.hidden = false;
  startProcessingState(skillScanLoading, [
    "Reviewing your Career Profile...",
    "Thinking about what's typical for these roles...",
    "Preparing a few questions...",
  ]);

  try {
    const res = await authedFetch("/api/career/skill-scan", { method: "POST" });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || `Request failed (${res.status})`);
    }
    const data = await res.json();

    skillScanState.categories = data.categories || [];
    skillScanState.history = [];
    skillScanState.roundNumber = 1;
    skillScanState.discoveredFacts = [];
    currentSkillScanQuestions = data.questions || [];

    document.getElementById("skill-scan-summary").textContent = data.analysis_summary || "";

    stopProcessingState(skillScanLoading);
    hideAllSkillScanStates();
    if (currentSkillScanQuestions.length === 0) {
      document.getElementById("skill-scan-complete-summary").textContent = data.analysis_summary || "";
      skillScanComplete.hidden = false;
    } else {
      renderSkillScanQuestionsBatch(currentSkillScanQuestions);
      skillScanQuestions.hidden = false;
    }
  } catch (err) {
    stopProcessingState(skillScanLoading);
    hideAllSkillScanStates();
    skillScanStart.hidden = false;
    alert(err.message || "Something went wrong starting the scan.");
  }
});

function renderSkillScanQuestionsBatch(questions) {
  const container = document.getElementById("skill-scan-questions-list");
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

function collectSkillScanAnswers() {
  return currentSkillScanQuestions.map((q) => {
    let answer;
    if (q.type === "detail") {
      const textarea = document.querySelector(`#skill-scan-questions-list textarea[data-qid="${q.id}"]`);
      answer = textarea ? textarea.value.trim() : "";
    } else {
      const selected = document.querySelector(`#skill-scan-questions-list input[name="${q.id}"]:checked`);
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

async function submitSkillScanAnswers(forceFinish) {
  const errorEl = document.getElementById("skill-scan-questions-error");
  errorEl.hidden = true;

  const answered = collectSkillScanAnswers();
  skillScanState.history.push(...answered);

  skillScanQuestions.hidden = true;
  skillScanLoading.hidden = false;
  startProcessingState(skillScanLoading, [
    "Reviewing your answers...",
    "Deciding what to ask next...",
  ]);

  const effectiveForceFinish = forceFinish || skillScanState.roundNumber >= SKILL_SCAN_MAX_ROUNDS;

  try {
    const res = await authedFetch("/api/career/job-discover", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        resume_data: { skill_scan: true },
        categories: skillScanState.categories,
        history: skillScanState.history,
        force_finish: effectiveForceFinish,
        round_number: skillScanState.roundNumber,
      }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || `Request failed (${res.status})`);
    }
    const data = await res.json();

    stopProcessingState(skillScanLoading);
    skillScanLoading.hidden = true;

    if (data.stage === "confirm") {
      skillScanState.discoveredFacts = data.discovered_facts || [];
      renderSkillScanReview();
      skillScanReview.hidden = false;
    } else {
      currentSkillScanQuestions = data.questions || [];
      skillScanState.roundNumber += 1;
      renderSkillScanQuestionsBatch(currentSkillScanQuestions);
      skillScanQuestions.hidden = false;
    }
  } catch (err) {
    stopProcessingState(skillScanLoading);
    skillScanQuestions.hidden = false;
    errorEl.textContent = err.message || "Something went wrong. Please try again.";
    errorEl.hidden = false;
  }
}

document.getElementById("skill-scan-questions-submit-btn").addEventListener("click", () => submitSkillScanAnswers(false));
document.getElementById("skill-scan-questions-finish-btn").addEventListener("click", () => submitSkillScanAnswers(true));

function renderSkillScanReview() {
  const container = document.getElementById("skill-scan-facts-list");
  container.innerHTML = "";

  if (skillScanState.discoveredFacts.length === 0) {
    const p = document.createElement("p");
    p.className = "hint";
    p.textContent = "Nothing new was confirmed this time.";
    container.appendChild(p);
    return;
  }

  skillScanState.discoveredFacts.forEach((fact, idx) => {
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
      skillScanState.discoveredFacts.splice(idx, 1);
      renderSkillScanReview();
    });
    header.appendChild(categorySpan);
    header.appendChild(removeBtn);
    card.appendChild(header);

    const textLabel = document.createElement("label");
    textLabel.className = "field";
    const textarea = document.createElement("textarea");
    textarea.rows = 2;
    textarea.value = fact.bullet_text || "";
    textarea.addEventListener("input", () => { fact.bullet_text = textarea.value; });
    textLabel.appendChild(textarea);
    card.appendChild(textLabel);

    const selectLabel = document.createElement("label");
    selectLabel.className = "field";
    const selectSpan = document.createElement("span");
    selectSpan.textContent = "Which role does this belong to?";
    const select = document.createElement("select");
    const noneOption = document.createElement("option");
    noneOption.value = "";
    noneOption.textContent = "Don't add this one";
    select.appendChild(noneOption);
    allExperiences.forEach((exp) => {
      const option = document.createElement("option");
      option.value = String(exp.id);
      option.textContent = exp.title + " — " + exp.organization;
      select.appendChild(option);
    });
    if (allExperiences.length > 0) {
      select.value = String(allExperiences[0].id);
    }
    fact.existingId = select.value ? Number(select.value) : null;
    select.addEventListener("change", () => { fact.existingId = select.value ? Number(select.value) : null; });
    selectLabel.appendChild(selectSpan);
    selectLabel.appendChild(select);
    card.appendChild(selectLabel);

    container.appendChild(card);
  });
}

document.getElementById("skill-scan-save-btn").addEventListener("click", async () => {
  const errorEl = document.getElementById("skill-scan-save-error");
  errorEl.hidden = true;
  const saveBtn = document.getElementById("skill-scan-save-btn");
  saveBtn.disabled = true;

  const toSave = skillScanState.discoveredFacts.filter((f) => f.existingId);

  try {
    if (toSave.length > 0) {
      const res = await authedFetch("/api/career/skill-scan-save", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          confirmed_facts: toSave.map((f) => ({ bullet_text: f.bullet_text, existing_id: f.existingId })),
        }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || "Couldn't save those changes.");
      }
    }

    hideAllSkillScanStates();
    skillScanStart.hidden = false;
    await loadExperiences();
  } catch (err) {
    errorEl.textContent = err.message || "Something went wrong saving.";
    errorEl.hidden = false;
  } finally {
    saveBtn.disabled = false;
  }
});

document.getElementById("skill-scan-cancel-btn").addEventListener("click", () => {
  hideAllSkillScanStates();
  skillScanStart.hidden = false;
});

document.getElementById("skill-scan-complete-ok-btn").addEventListener("click", () => {
  hideAllSkillScanStates();
  skillScanStart.hidden = false;
});
