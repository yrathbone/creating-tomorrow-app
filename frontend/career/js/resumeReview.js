// Resume-driven Career Profile ingestion: upload -> extract roles -> the
// same discovery-interview loop Elevate uses (elevate.js's own pattern,
// mirrored here rather than reinvented) -> review/edit -> save. Relies on
// authedFetch()/currentAccessToken/loadExperiences() from login.js, and
// startProcessingState()/stopProcessingState() from loading.js - all
// loaded before this file in login.html.

const resumeState = {
  roles: [],
  education: [],
  certifications: [],
  categories: [],
  history: [],
  roundNumber: 1,
  discoveredFacts: [],
  skills: [],
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

// Matches newly extracted resume data against what's already in the
// profile (allExperiences/allEducation/allCertifications, from login.js)
// so uploading another resume consolidates into the same roles instead of
// creating duplicates every time. Heuristic, not exact - always shown as
// an editable dropdown so the candidate has final say, never applied
// silently.
function normalizeKey(s) {
  return (s || "").toLowerCase().replace(/[^a-z0-9]+/g, " ").trim();
}

// Shared fuzzy scorer for two normalized strings - exact match scores
// highest, then substring containment (handles phrasing like "Treasury
// Management Officer - HHN" vs "Treasury Management Officer" or
// "Google Project Management (Professional Certificate)" vs "Google
// Project Management"), then significant word overlap. 0 means no
// meaningful similarity.
function fuzzyTextScore(a, b) {
  if (!a || !b) return 0;
  if (a === b) return 3;
  if (a.includes(b) || b.includes(a)) return 2;
  const aWords = new Set(a.split(" ").filter(Boolean));
  const overlap = b.split(" ").filter((w) => w && aWords.has(w)).length;
  return overlap >= 2 ? 1 : 0;
}

function findBestExperienceMatch(role) {
  const newOrg = normalizeKey(role.organization);
  const newTitle = normalizeKey(role.title);
  if (!newOrg) return null;
  let best = null;
  let bestScore = 0;
  for (const existing of allExperiences) {
    if (normalizeKey(existing.organization) !== newOrg) continue;
    const score = fuzzyTextScore(normalizeKey(existing.title), newTitle);
    if (score > bestScore) { bestScore = score; best = existing; }
  }
  return bestScore > 0 ? best : null;
}

function findBestEducationMatch(entry) {
  const newInstitution = normalizeKey(entry.institution);
  if (!newInstitution) return null;
  const newDegree = normalizeKey(entry.degree);
  let best = null;
  let bestScore = 0;
  for (const existing of allEducation) {
    if (normalizeKey(existing.institution) !== newInstitution) continue;
    const existingDegree = normalizeKey(existing.degree);
    // Institution alone isn't enough - the same school can genuinely have
    // several distinct real degrees (this is exactly the bug that caused
    // duplicate-looking-but-actually-different UMGC entries to collide).
    // If either side is missing a degree, treat institution match as
    // weakly sufficient rather than losing the match entirely.
    const score = (!newDegree || !existingDegree) ? 1 : fuzzyTextScore(existingDegree, newDegree);
    if (score > bestScore) { bestScore = score; best = existing; }
  }
  return bestScore > 0 ? best : null;
}

function findBestCertificationMatch(entry) {
  const newName = normalizeKey(entry.name);
  if (!newName) return null;
  let best = null;
  let bestScore = 0;
  for (const existing of allCertifications) {
    const score = fuzzyTextScore(normalizeKey(existing.name), newName);
    if (score > bestScore) { bestScore = score; best = existing; }
  }
  return bestScore > 0 ? best : null;
}

// Builds the "which existing record is this?" dropdown used on every
// role/education/certification review card. onChange receives the
// selected existing id, or null for "add as new".
function makeMatchSelect(existingOptions, bestMatch, onChange) {
  const label = document.createElement("label");
  label.className = "field";
  const span = document.createElement("span");
  span.textContent = "This is:";
  const select = document.createElement("select");

  const newOption = document.createElement("option");
  newOption.value = "";
  newOption.textContent = "➕ Add as a new entry";
  select.appendChild(newOption);

  for (const opt of existingOptions) {
    const option = document.createElement("option");
    option.value = String(opt.id);
    option.textContent = opt.label;
    select.appendChild(option);
  }

  select.value = bestMatch ? String(bestMatch.id) : "";
  onChange(select.value ? Number(select.value) : null);
  select.addEventListener("change", () => {
    onChange(select.value ? Number(select.value) : null);
  });

  label.appendChild(span);
  label.appendChild(select);
  return label;
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

function makeTextareaField(labelText, value, onInput) {
  const label = document.createElement("label");
  label.className = "field";
  const span = document.createElement("span");
  span.textContent = labelText;
  const textarea = document.createElement("textarea");
  textarea.rows = 5;
  textarea.value = value || "";
  textarea.addEventListener("input", () => onInput(textarea.value));
  label.appendChild(span);
  label.appendChild(textarea);
  return label;
}

function makeSelectField(labelText, value, options, onInput) {
  const label = document.createElement("label");
  label.className = "field";
  const span = document.createElement("span");
  span.textContent = labelText;
  const select = document.createElement("select");
  for (const opt of options) {
    const option = document.createElement("option");
    option.value = opt.value;
    option.textContent = opt.label;
    select.appendChild(option);
  }
  select.value = value || "";
  select.addEventListener("change", () => onInput(select.value));
  label.appendChild(span);
  label.appendChild(select);
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
  resumeState.education = draft.education || [];
  resumeState.certifications = draft.certifications || [];
  resumeState.categories = draft.categories || [];
  resumeState.history = draft.history || [];
  resumeState.discoveredFacts = draft.discovered_facts || [];
  resumeState.skills = [];  // not kept in the saved draft; re-import to see skills again
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
  // A file wins; otherwise pasted text is sent the same way, as a small .txt file.
  const pasted = document.getElementById("resume-paste-text").value.trim();
  let uploadFile = fileInput.files.length ? fileInput.files[0] : null;
  if (!uploadFile && pasted.length >= 100) {
    uploadFile = new File([pasted], "pasted-profile.txt", { type: "text/plain" });
  }
  if (!uploadFile) {
    showResumeError(resumeUploadError, pasted ? "That's a bit short. Paste more of your profile or resume." : "Please choose a file, or paste your profile or resume text.");
    return;
  }

  const formData = new FormData();
  formData.append("resume_file", uploadFile);

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
      throw new Error(formatErrorDetail(err.detail, `Request failed (${res.status})`));
    }
    const data = await res.json();

    resumeState.roles = data.roles || [];
    resumeState.education = data.education || [];
    resumeState.certifications = data.certifications || [];
    resumeState.categories = data.categories || [];
    resumeState.history = [];
    resumeState.roundNumber = 1;
    resumeState.discoveredFacts = [];
    resumeState.skills = data.skills || [];
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
      throw new Error(formatErrorDetail(err.detail, `Request failed (${res.status})`));
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

    const roleOptions = allExperiences.map((e) => ({
      id: e.id,
      label: e.organization + " — " + e.title + (e.start_date ? " (" + e.start_date + ")" : ""),
    }));
    card.appendChild(makeMatchSelect(roleOptions, findBestExperienceMatch(role), (id) => {
      role.existing_id = id;
    }));

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

  renderResumeEducation();
  renderResumeCertifications();
  renderResumeSkills();
  renderResumeFacts();
  renderImportMatchNote();
}

function renderResumeEducation() {
  const container = document.getElementById("resume-education-list");
  if (!container) return;
  container.innerHTML = "";
  document.getElementById("resume-education-block").hidden = resumeState.education.length === 0;

  resumeState.education.forEach((entry, idx) => {
    const card = document.createElement("div");
    card.className = "entry-summary-card";

    const header = document.createElement("div");
    header.className = "entry-summary-header";
    const label = document.createElement("span");
    label.className = "hint";
    label.textContent = "Education " + (idx + 1);
    const removeBtn = document.createElement("button");
    removeBtn.type = "button";
    removeBtn.className = "entry-remove-btn";
    removeBtn.textContent = "Remove";
    removeBtn.addEventListener("click", () => {
      resumeState.education.splice(idx, 1);
      renderResumeEducation();
    });
    header.appendChild(label);
    header.appendChild(removeBtn);
    card.appendChild(header);

    const eduOptions = allEducation.map((e) => ({
      id: e.id,
      label: e.institution + (e.degree ? " — " + e.degree : ""),
    }));
    card.appendChild(makeMatchSelect(eduOptions, findBestEducationMatch(entry), (id) => {
      entry.existing_id = id;
    }));

    card.appendChild(makeTextField("Institution", entry.institution, (v) => { entry.institution = v; }));
    card.appendChild(makeTextField("Degree", entry.degree, (v) => { entry.degree = v; }));
    card.appendChild(makeTextField("Field of study", entry.field_of_study, (v) => { entry.field_of_study = v; }));
    card.appendChild(makeTextField("Graduation date", entry.graduation_date, (v) => { entry.graduation_date = v; }));

    container.appendChild(card);
  });
}

function renderResumeCertifications() {
  const container = document.getElementById("resume-certifications-list");
  if (!container) return;
  container.innerHTML = "";
  document.getElementById("resume-certifications-block").hidden = resumeState.certifications.length === 0;

  resumeState.certifications.forEach((entry, idx) => {
    const card = document.createElement("div");
    card.className = "entry-summary-card";

    const header = document.createElement("div");
    header.className = "entry-summary-header";
    const label = document.createElement("span");
    label.className = "hint";
    label.textContent = "Certification " + (idx + 1);
    const removeBtn = document.createElement("button");
    removeBtn.type = "button";
    removeBtn.className = "entry-remove-btn";
    removeBtn.textContent = "Remove";
    removeBtn.addEventListener("click", () => {
      resumeState.certifications.splice(idx, 1);
      renderResumeCertifications();
    });
    header.appendChild(label);
    header.appendChild(removeBtn);
    card.appendChild(header);

    const certOptions = allCertifications.map((c) => ({
      id: c.id,
      label: c.name + (c.issuer ? " — " + c.issuer : ""),
    }));
    card.appendChild(makeMatchSelect(certOptions, findBestCertificationMatch(entry), (id) => {
      entry.existing_id = id;
    }));

    card.appendChild(makeTextField("Certification name", entry.name, (v) => { entry.name = v; }));
    card.appendChild(makeTextField("Issuer", entry.issuer, (v) => { entry.issuer = v; }));
    card.appendChild(makeTextField("Date", entry.date, (v) => { entry.date = v; }));

    container.appendChild(card);
  });
}

// Skills the document lists that are NOT already in the profile. Skills that
// match one already saved are counted and hidden, so nothing is duplicated.
// Each new skill is a checkbox the candidate controls; nothing saves until
// they press Save.
function skillAlreadySaved(name) {
  const key = normalizeKey(name);
  return (typeof allSkills !== "undefined" ? allSkills : []).some((s) => normalizeKey(s.name) === key);
}

function renderResumeSkills() {
  const block = document.getElementById("resume-skills-block");
  const list = document.getElementById("resume-skills-list");
  const note = document.getElementById("resume-skills-note");
  list.textContent = "";
  const found = resumeState.skills || [];
  block.hidden = found.length === 0;
  if (!found.length) return;

  const fresh = found.filter((n) => !skillAlreadySaved(n));
  resumeState.newSkills = fresh;
  const dup = found.length - fresh.length;
  note.textContent = fresh.length
    ? fresh.length + " new skill" + (fresh.length === 1 ? "" : "s") + " from your document. Untick any you don't want." + (dup ? " " + dup + " you already have " + (dup === 1 ? "is" : "are") + " not shown." : "")
    : "All " + found.length + " skills in your document are already in your profile. Nothing to add.";
  for (const name of fresh) {
    const li = document.createElement("li");
    const label = document.createElement("label");
    const box = document.createElement("input");
    box.type = "checkbox";
    box.checked = true;
    box.dataset.skill = name;
    label.appendChild(box);
    label.appendChild(document.createTextNode(" " + name));
    li.appendChild(label);
    list.appendChild(li);
  }
}

// One line up top: how much of this document is already in the profile.
function renderImportMatchNote() {
  const el = document.getElementById("resume-match-note");
  const parts = [];
  const roleMatches = resumeState.roles.filter((r) => findBestExperienceMatch(r)).length;
  if (resumeState.roles.length) parts.push(roleMatches + " of " + resumeState.roles.length + " roles match ones you already have");
  const eduMatches = resumeState.education.filter((e) => findBestEducationMatch(e)).length;
  if (resumeState.education.length) parts.push(eduMatches + " of " + resumeState.education.length + " education entries");
  const certMatches = resumeState.certifications.filter((c) => findBestCertificationMatch(c)).length;
  if (resumeState.certifications.length) parts.push(certMatches + " of " + resumeState.certifications.length + " certifications");
  el.hidden = parts.length === 0;
  el.textContent = parts.length ? "Already in your profile: " + parts.join(", ") + ". Matches are preselected as updates, so they won't be duplicated; change any you disagree with." : "";
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
        education: resumeState.education,
        certifications: resumeState.certifications,
        confirmed_facts: resumeState.discoveredFacts.map((f) => ({
          bullet_text: f.bullet_text,
          role_index: f.roleIndex,
        })),
      }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(formatErrorDetail(err.detail, `Request failed (${res.status})`));
    }
    const saved = await res.json();

    // New skills the candidate left ticked, saved one by one through the normal skills route.
    let skillsAdded = 0;
    for (const box of document.querySelectorAll("#resume-skills-list input[type=checkbox]")) {
      if (!box.checked) continue;
      const skillRes = await authedFetch("/api/career/skills", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: box.dataset.skill, source_text: null, experience_id: null }),
      });
      if (skillRes.ok) skillsAdded += 1;
    }

    resumeReviewState.hidden = true;
    resumeState.skills = [];
    resumeState.roles = [];
    resumeState.education = [];
    resumeState.certifications = [];
    resumeState.discoveredFacts = [];
    resumeState.history = [];
    resumeState.roundNumber = 1;
    currentDraft = null;

    const parts = [];
    if (saved.created_count) parts.push(saved.created_count + " new");
    if (saved.updated_count) parts.push(saved.updated_count + " updated in your existing profile");
    if (skillsAdded) parts.push(skillsAdded + (skillsAdded === 1 ? " skill" : " skills") + " added");
    document.getElementById("resume-save-summary-text").textContent =
      parts.length ? "Saved to your Career Profile: " + parts.join(", ") + "." : "Your changes were saved to your Career Profile.";
    document.getElementById("resume-save-summary").hidden = false;

    await loadExperiences();
    await loadEducation();
    await loadCertifications();
    if (skillsAdded && typeof loadSkills === "function") await loadSkills();
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
