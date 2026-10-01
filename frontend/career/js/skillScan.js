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
  analysisSummary: "",
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
      throw new Error(formatErrorDetail(err.detail, `Request failed (${res.status})`));
    }
    const data = await res.json();

    skillScanState.categories = data.categories || [];
    skillScanState.history = [];
    skillScanState.roundNumber = 1;
    skillScanState.discoveredFacts = [];
    currentSkillScanQuestions = data.questions || [];

    document.getElementById("skill-scan-summary").textContent = data.analysis_summary || "";
    skillScanState.analysisSummary = data.analysis_summary || "";

    stopProcessingState(skillScanLoading);
    hideAllSkillScanStates();
    if (currentSkillScanQuestions.length === 0) {
      document.getElementById("skill-scan-complete-summary").textContent = data.analysis_summary || "";
      skillScanComplete.hidden = false;
      if (typeof loadScanHistory === "function") loadScanHistory();
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
      throw new Error(formatErrorDetail(err.detail, `Request failed (${res.status})`));
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

    // This becomes a real Skill row, not a bullet appended to a role's
    // description - name is the skill itself (editable; the AI's
    // category is a reasonable starting label, not necessarily the final
    // one), source_text is the "how it was used" context.
    fact.name = fact.category || "";
    fact.include = true;

    const nameLabel = document.createElement("label");
    nameLabel.className = "field";
    const nameSpan = document.createElement("span");
    nameSpan.textContent = "Skill";
    const nameInput = document.createElement("input");
    nameInput.type = "text";
    nameInput.value = fact.name;
    nameInput.addEventListener("input", () => { fact.name = nameInput.value; });
    nameLabel.appendChild(nameSpan);
    nameLabel.appendChild(nameInput);
    card.appendChild(nameLabel);

    const textLabel = document.createElement("label");
    textLabel.className = "field";
    const textSpan = document.createElement("span");
    textSpan.textContent = "How it was used (optional)";
    const textarea = document.createElement("textarea");
    textarea.rows = 2;
    textarea.value = fact.bullet_text || "";
    textarea.addEventListener("input", () => { fact.bullet_text = textarea.value; });
    textLabel.appendChild(textSpan);
    textLabel.appendChild(textarea);
    card.appendChild(textLabel);

    const selectLabel = document.createElement("label");
    selectLabel.className = "field";
    const selectSpan = document.createElement("span");
    selectSpan.textContent = "Which role does this belong to? (optional)";
    const select = document.createElement("select");
    const noneOption = document.createElement("option");
    noneOption.value = "";
    // Deliberately the default - a past bug here silently defaulted to
    // whatever role was most recently added, regardless of relevance.
    // "Not tied to one role" is always correct as a default; a specific
    // role is only ever chosen explicitly.
    noneOption.textContent = "Not tied to one specific role";
    select.appendChild(noneOption);
    allExperiences.forEach((exp) => {
      const option = document.createElement("option");
      option.value = String(exp.id);
      option.textContent = exp.title + " — " + exp.organization;
      select.appendChild(option);
    });
    fact.experienceId = null;
    select.addEventListener("change", () => { fact.experienceId = select.value ? Number(select.value) : null; });
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

  // Every fact still in the list gets saved - "Remove" (above) is how a
  // candidate excludes one, not leaving a dropdown unset. Not being tied
  // to a specific role is a valid, intentional choice, not "skip this."
  const toSave = skillScanState.discoveredFacts.filter((f) => (f.name || "").trim());

  try {
    if (toSave.length > 0) {
      const res = await authedFetch("/api/career/skill-scan-save", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          confirmed_facts: toSave.map((f) => ({
            name: f.name.trim(),
            source_text: (f.bullet_text || "").trim(),
            experience_id: f.experienceId || null,
          })),
          analysis_summary: skillScanState.analysisSummary,
          categories: skillScanState.categories,
        }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(formatErrorDetail(err.detail, "Couldn't save those changes."));
      }
    }

    hideAllSkillScanStates();
    skillScanStart.hidden = false;
    await loadSkills();
    if (typeof loadScanHistory === "function") loadScanHistory();
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
