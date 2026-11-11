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
  scanHistoryId: null,
  jobFit: null,
  jobTitle: "",
  resumeVersionId: null,
  opportunityId: null,
};
let currentJobQuestions = [];
const JOB_MAX_ROUNDS = 4;

const jobTargetEmpty = document.getElementById("job-target-empty");
const jobInputState = document.getElementById("job-input-state");
const jobLoadingState = document.getElementById("job-loading-state");
const jobMatchState = document.getElementById("job-match-state");
const jobQuestionsState = document.getElementById("job-questions-state");
const jobBuildFormState = document.getElementById("job-build-form-state");
const jobKeywordsState = document.getElementById("job-keywords-state");
const jobBuildLoadingState = document.getElementById("job-build-loading-state");
const jobBuildDoneState = document.getElementById("job-build-done-state");

// Keyboard focus and announcements (Phase 02 batch 2.6B), the same pattern as generalResume.js. A button that is pressed and then
// hidden would leave focus on the page body, so focus stays inside this card, and a persistent polite status region says what happened.
const jobStatus = document.getElementById("job-status");
const jobHeading = document.getElementById("job-card-heading");
const JOB_BUILD_FORM_MESSAGE = "Add your name and contact line, then build your resume.";

function focusJob(el) {
  if (el && typeof el.focus === "function") el.focus({ preventScroll: true });
}

function announceJob(text) {
  if (jobStatus) jobStatus.textContent = text;
}

// True only when the button was pressed from the keyboard (it shows a keyboard focus ring, :focus-visible). A mouse or touch tap, or a
// script's click, must not move focus into a field (a phone would pop up its on-screen keyboard).
function jobKeyboardPress(event) {
  const button = event && event.currentTarget;
  return !!(button && typeof button.matches === "function" && button.matches(":focus-visible"));
}

// A slow step starts: empty the status (so the next message is announced again) and park focus on the progress card.
function jobStepStarted(panel) {
  announceJob("");
  focusJob(panel);
}

// A step finished: say so once, and put focus on the card heading.
function jobStepDone(message) {
  announceJob(message);
  focusJob(jobHeading);
}

// Whatever is typed here prints at the top of the resume exactly as written
// (a version label like "Yovana Rathbone 3" or a missing email both hurt a
// resume), so ask once before building. Also used by generalResume.js.
function confirmHeaderDetails(name, contact) {
  const problems = [];
  if (/\d/.test(name)) problems.push('Your name contains a number ("' + name + '") and it will print on the resume exactly like that.');
  if (!contact.includes("@")) problems.push("Your contact line has no email address. Recruiters and applicant tracking systems look for one.");
  if (problems.length === 0) return true;
  return window.confirm(problems.join("\n\n") + "\n\nBuild the resume anyway?\n(Cancel to go back and fix it.)");
}

function hideAllJobStates() {
  jobTargetEmpty.hidden = true;
  jobInputState.hidden = true;
  jobLoadingState.hidden = true;
  jobMatchState.hidden = true;
  jobQuestionsState.hidden = true;
  jobBuildFormState.hidden = true;
  jobKeywordsState.hidden = true;
  jobBuildLoadingState.hidden = true;
  jobBuildDoneState.hidden = true;
}

document.getElementById("job-target-add-btn").addEventListener("click", (event) => {
  const fromKeyboard = jobKeyboardPress(event); // read first: once the button is hidden the browser no longer says it had a keyboard focus ring
  clearOpportunityContext(); // a plain "Add a job" is not linked to any saved link
  hideAllJobStates();
  jobInputState.hidden = false;
  if (fromKeyboard) focusJob(document.getElementById("job-description-input"));
});

document.getElementById("job-cancel-btn").addEventListener("click", () => {
  hideAllJobStates();
  jobTargetEmpty.hidden = false;
  focusJob(document.getElementById("job-target-add-btn"));
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
  jobStepStarted(jobLoadingState);
  startProcessingState(jobLoadingState, [
    "Reading the job posting...",
    "Comparing it to your Career Profile...",
    "Identifying what’s worth exploring...",
  ]);

  try {
    const res = await authedFetch("/api/career/job-compare", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(jobState.opportunityId ? { job_description: jobDescription, opportunity_id: jobState.opportunityId } : { job_description: jobDescription }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(formatErrorDetail(err.detail, `Request failed (${res.status})`));
    }
    const data = await res.json();

    jobState.matchReport = data.match_report;
    jobState.categories = data.categories || [];
    jobState.history = [];
    jobState.roundNumber = 1;
    jobState.discoveredFacts = [];
    jobState.scanHistoryId = data.scan_history_id || null;
    currentJobQuestions = data.questions || [];

    renderJobMatch(data.match_report);
    jobState.jobFit = data.job_fit || null;
    jobState.jobTitle = data.job_title || "";
    renderJobFit(jobState.jobFit);

    stopProcessingState(jobLoadingState);
    jobLoadingState.hidden = true;
    jobMatchState.hidden = false;
    jobStepDone("Job comparison ready.");
  } catch (err) {
    stopProcessingState(jobLoadingState);
    hideAllJobStates();
    jobInputState.hidden = false;
    errorEl.textContent = err.message || "Something went wrong. Please try again.";
    errorEl.hidden = false;
    focusJob(document.getElementById("job-compare-btn")); // the message above is an alert; focus is back where the person can try again
  }
});

// Job Fit: does this JOB match the candidate (computed on the server from the
// comparison's requirement lists). Shown as a letter and a band, with what would
// honestly close the biggest gaps. Separate from the resume's Keyword Match grade.
function renderJobFit(fit) {
  const block = document.getElementById("job-fit-block");
  const closeBlock = document.getElementById("job-fit-close-block");
  const closeList = document.getElementById("job-fit-close-list");
  closeList.textContent = "";
  block.hidden = !fit;
  closeBlock.hidden = true;
  block.className = "match-grade" + (fit ? " match-grade-" + fit.letter.toLowerCase() : "");
  if (!fit) return;
  document.getElementById("job-fit-letter").textContent = fit.letter;
  document.getElementById("job-fit-title").textContent = "Job Fit: " + fit.title + " (" + fit.band + " of what the posting asks)";
  document.getElementById("job-fit-verdict").textContent = fit.verdict;
  const gaps = fit.open_gaps || [];
  closeBlock.hidden = gaps.length === 0;
  for (const g of gaps) {
    const li = document.createElement("li");
    li.textContent = g.requirement + (g.importance === "required" ? " (required)" : " (preferred)") + (g.how_to_close ? " — " + g.how_to_close : "");
    closeList.appendChild(li);
  }
}

// After the gap interview, gaps the candidate confirmed count as met.
async function refreshJobFit() {
  const note = document.getElementById("job-fit-after");
  note.hidden = true;
  if (!jobState.jobFit || !jobState.matchReport || !jobState.discoveredFacts.length) return;
  try {
    const res = await authedFetch("/api/career/job-fit", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ match_report: jobState.matchReport, confirmed_facts: jobState.discoveredFacts }),
    });
    if (!res.ok) return;
    const data = await res.json();
    if (!data.job_fit) return;
    const before = jobState.jobFit;
    jobState.jobFit = data.job_fit;
    renderJobFit(data.job_fit);
    note.textContent = "Job Fit after your answers: " + data.job_fit.letter + " (" + data.job_fit.band + ")" +
      (data.job_fit.letter !== before.letter ? ", up from " + before.letter + "." : ".");
    note.hidden = false;
  } catch (err) {
    // The fit is informational; never block building the resume on it.
  }
}

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
      li.textContent = g.requirement + (g.importance ? " (" + g.importance + ")" : "") + " — " + g.explanation;
      gapsList.appendChild(li);
    });
  }
}

document.getElementById("job-start-interview-btn").addEventListener("click", () => {
  hideAllJobStates();
  if (currentJobQuestions.length) {
    renderJobQuestionsBatch(currentJobQuestions);
    jobQuestionsState.hidden = false;
    jobStepDone("Questions ready.");
  } else {
    showJobBuildForm();
    jobStepDone(JOB_BUILD_FORM_MESSAGE);
  }
});

document.getElementById("job-skip-interview-btn").addEventListener("click", () => {
  hideAllJobStates();
  showJobBuildForm();
  jobStepDone(JOB_BUILD_FORM_MESSAGE);
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
  jobStepStarted(jobLoadingState);
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
      throw new Error(formatErrorDetail(err.detail, `Request failed (${res.status})`));
    }
    const data = await res.json();

    stopProcessingState(jobLoadingState);
    jobLoadingState.hidden = true;

    if (data.stage === "confirm") {
      jobState.discoveredFacts = data.discovered_facts || [];
      await refreshJobFit();
      showJobBuildForm();
      jobStepDone(JOB_BUILD_FORM_MESSAGE);
    } else {
      currentJobQuestions = data.questions || [];
      jobState.roundNumber += 1;
      renderJobQuestionsBatch(currentJobQuestions);
      jobQuestionsState.hidden = false;
      jobStepDone("More questions ready.");
    }
  } catch (err) {
    stopProcessingState(jobLoadingState);
    jobLoadingState.hidden = true; // the progress card no longer stays on screen above the questions after a failure
    jobQuestionsState.hidden = false;
    errorEl.textContent = err.message || "Something went wrong. Please try again.";
    errorEl.hidden = false;
    focusJob(document.getElementById("job-questions-submit-btn"));
  }
}

document.getElementById("job-questions-submit-btn").addEventListener("click", () => submitJobAnswers(false));
document.getElementById("job-questions-finish-btn").addEventListener("click", () => submitJobAnswers(true));

function showJobBuildForm() {
  hideAllJobStates();
  jobBuildFormState.hidden = false;
  prefillResumeHeader(document.getElementById("job-build-name"), document.getElementById("job-build-contact"));
  renderFactsReview();
}

// "How your answers will read": every sentence made from the candidate's answers, shown for editing before it is used. People often
// say what they were ("cashier") rather than what they did ("balanced an open cash drawer for 5 years"), so a short or stock
// sentence gets a nudge to be more specific. Edits and removals go straight into jobState.discoveredFacts, which the build sends.
const STOCK_FACT = /^Has real hands-on experience with /i;
function factNeedsDetail(text) {
  const words = (text || "").trim().split(/\s+/).filter(Boolean).length;
  return words < 9 || STOCK_FACT.test(text || "");
}
function renderFactsReview() {
  const block = document.getElementById("job-facts-review");
  const list = document.getElementById("job-facts-list");
  list.textContent = "";
  block.hidden = jobState.discoveredFacts.length === 0;
  jobState.discoveredFacts.forEach((fact) => {
    const li = document.createElement("li");
    li.className = "facts-review-item";
    const label = document.createElement("strong");
    label.textContent = fact.category || "Your answer";
    li.appendChild(label);

    const box = document.createElement("textarea");
    box.rows = 2;
    box.value = fact.bullet_text || "";
    box.setAttribute("aria-label", "Sentence for " + (fact.category || "this answer"));
    li.appendChild(box);

    const nudge = document.createElement("p");
    nudge.className = "hint facts-review-nudge";
    nudge.textContent = "Add detail if you can: what exactly you did, how much or how often, for how long, for whom.";
    nudge.hidden = !factNeedsDetail(box.value);
    li.appendChild(nudge);

    box.addEventListener("input", () => {
      fact.bullet_text = box.value;
      nudge.hidden = !factNeedsDetail(box.value);
    });

    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "entry-remove-btn";
    remove.textContent = "Remove";
    remove.addEventListener("click", () => {
      jobState.discoveredFacts = jobState.discoveredFacts.filter((f) => f !== fact);
      renderFactsReview();
    });
    li.appendChild(remove);
    list.appendChild(li);
  });
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
  if (!confirmHeaderDetails(name, contact)) return;

  hideAllJobStates();
  jobBuildLoadingState.hidden = false;
  jobStepStarted(jobBuildLoadingState);
  startProcessingState(jobBuildLoadingState, [
    "Reading the posting’s key terms...",
    "Matching them to your experience...",
    "Writing your resume...",
    "Double-checking nothing was missed...",
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
        scan_history_id: jobState.scanHistoryId,
        qa_history: jobState.history,
      }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(formatErrorDetail(err.detail, `Request failed (${res.status})`));
    }
    const data = await res.json();
    jobState.tailoredResumeData = data.resume_data;
    jobState.resumeVersionId = data.resume_version_id || null;
    resetAppliedBlock();
    renderRoleSelection(data.role_selection || []);
    renderTermReport(data.term_report || []);
    renderMatchGrade(data.term_report || [], data.ats_match || null);
    loadSuggestions();
    renderTruthNotice(data.truth_notice || (data.resume_data && data.resume_data.truth_review && data.resume_data.truth_review.truth_notice));

    stopProcessingState(jobBuildLoadingState);
    jobBuildLoadingState.hidden = true;
    jobBuildDoneState.hidden = false;
    showOpportunityApproval();
    if (typeof loadOpportunities === "function") loadOpportunities(); // the saved link's approval state is read again from the server
    carryLayoutChoice("job-build-layout", "job-resume-template");
    if (typeof loadScanHistory === "function") loadScanHistory();
    if (typeof loadResumeVersions === "function") loadResumeVersions();
    jobStepDone("Your tailored resume is ready.");
  } catch (err) {
    stopProcessingState(jobBuildLoadingState);
    hideAllJobStates();
    jobBuildFormState.hidden = false;
    errorEl.textContent = err.message || "Something went wrong building your resume.";
    errorEl.hidden = false;
    focusJob(document.getElementById("job-build-btn"));
  }
});

// Optional keyword check before building: posting terms that are not in the
// profile yet, each with the candidate's own choice - save it as a Skill
// (optionally under a role, with a sentence on how it was used), use it for
// this resume only, or skip. Nothing is saved until "Save my choices", and
// nothing is assumed: "related" terms are only pre-selected as a suggestion.
let keywordTerms = [];
let keywordCovered = { exact: [], related: [], alternatives: [], count: 0 };

document.getElementById("job-keyword-check-btn").addEventListener("click", async () => {
  const errorEl = document.getElementById("job-build-error");
  errorEl.hidden = true;

  hideAllJobStates();
  jobLoadingState.hidden = false;
  jobStepStarted(jobLoadingState);
  startProcessingState(jobLoadingState, [
    "Reading the posting’s key terms...",
    "Checking them against your profile...",
  ]);

  try {
    const res = await authedFetch("/api/career/job-keyword-check", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ job_description: jobState.jobDescription, confirmed_facts: jobState.discoveredFacts, scan_history_id: jobState.scanHistoryId }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(formatErrorDetail(err.detail, `Request failed (${res.status})`));
    }
    const data = await res.json();
    keywordTerms = data.terms || [];
    keywordCovered = { exact: data.covered_exact || [], related: data.covered_related || [], alternatives: data.alternatives_met || [], count: data.already_covered || 0 };

    stopProcessingState(jobLoadingState);
    jobLoadingState.hidden = true;
    if (keywordTerms.length === 0) {
      showJobBuildForm();
      showKeywordNote("Every key term in the posting is already backed by your profile" + (data.already_covered ? " (" + data.already_covered + ")" : "") + ". Nothing to add.");
      focusJob(jobHeading);
      return;
    }
    renderKeywordCards(data.already_covered || 0);
    jobKeywordsState.hidden = false;
    jobStepDone("Keyword choices ready.");
  } catch (err) {
    stopProcessingState(jobLoadingState);
    showJobBuildForm();
    errorEl.textContent = err.message || "Something went wrong checking the keywords.";
    errorEl.hidden = false;
    focusJob(document.getElementById("job-keyword-check-btn"));
  }
});

// Free-text "add a term" on the build screen: a term the candidate types is
// confirmed by them, so it counts as evidence and the build must print it
// when the posting asks for it. Either one resume only, or saved to Skills.
async function addExtraTerm(saveToSkills) {
  const input = document.getElementById("job-extra-term-input");
  const errorEl = document.getElementById("job-build-error");
  errorEl.hidden = true;
  const term = input.value.trim();
  if (!term) return;
  if (term.split(/\s+/).length > 4) {
    errorEl.textContent = "Keep it to a short keyword (up to 4 words), like \"Sales process\".";
    errorEl.hidden = false;
    return;
  }
  if (saveToSkills) {
    const res = await authedFetch("/api/career/skills", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: term, source_text: null, experience_id: null }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      errorEl.textContent = formatErrorDetail(err.detail, "Couldn’t save that skill.");
      errorEl.hidden = false;
      return;
    }
    if (typeof loadSkills === "function") await loadSkills();
    showKeywordNote('"' + term + '" saved to your Skills.');
  } else {
    jobState.discoveredFacts = jobState.discoveredFacts.filter((f) => f.source !== "typed_term" || f.category.toLowerCase() !== term.toLowerCase());
    jobState.discoveredFacts.push({
      category: term,
      bullet_text: "Has real hands-on experience with " + term + ".",
      source: "typed_term",
    });
    showKeywordNote('"' + term + '" added for this resume only.');
  }
  input.value = "";
}

document.getElementById("job-extra-term-resume-btn").addEventListener("click", () => addExtraTerm(false));
document.getElementById("job-extra-term-skill-btn").addEventListener("click", () => addExtraTerm(true));

function showKeywordNote(text) {
  const note = document.getElementById("job-keyword-saved-note");
  note.textContent = text;
  note.hidden = !text;
  announceJob(text); // the note is plain text that appears and disappears, so it is also said through the status region
}

// The terms the profile already backs are listed (collapsed) with the evidence found, and are never asked about.
function renderCoveredTerms() {
  const details = document.getElementById("job-keywords-covered");
  const list = document.getElementById("job-keywords-covered-list");
  list.textContent = "";
  const total = keywordCovered.exact.length + keywordCovered.related.length;
  details.hidden = total === 0;
  if (!total) return;
  document.getElementById("job-keywords-covered-summary").textContent =
    "Already backed by your profile (" + total + "): see what we found";
  const add = (item, why, chip) => {
    const li = document.createElement("li");
    const name = document.createElement("strong");
    name.textContent = item.term + (item.importance && item.importance !== "mentioned" ? " (" + item.importance + ")" : "");
    li.appendChild(name);
    li.appendChild(document.createTextNode(" "));
    li.appendChild(evidenceChip(chip));
    const note = document.createElement("span");
    note.className = "hint";
    note.textContent = " — " + why;
    li.appendChild(note);
    list.appendChild(li);
  };
  keywordCovered.related.forEach((t) => add(t, "Your profile shows: " + t.evidence, "other"));
  keywordCovered.exact.forEach((t) => add(t, "this wording is in your profile", "backed"));
  keywordCovered.alternatives.forEach((g) => {
    add({ term: g.terms.join(" or "), importance: g.importance },
      "the posting accepts any one of these; met through " + g.met_by + (g.evidence ? " (" + g.evidence + ")" : ""), "backed");
  });
}

function renderKeywordCards(alreadyCovered) {
  const asked = keywordTerms.length;
  const listed = keywordCovered.exact.length + keywordCovered.related.length; // the number the list below shows
  document.getElementById("job-keywords-intro").textContent =
    (listed || alreadyCovered) + " key terms are already backed by your profile (listed below, nothing to answer). " +
    "Only " + asked + " " + (asked === 1 ? "term needs" : "terms need") + " your answer: tell me honestly whether each is true for you. " +
    "Anything you skip stays off your resume.";
  renderCoveredTerms();
  const groups = groupEvidence({ terms: keywordTerms, covered_exact: keywordCovered.exact, covered_related: keywordCovered.related, alternatives_met: keywordCovered.alternatives });
  renderEvidenceTiles(document.getElementById("job-keywords-tiles"), groups.tiles);
  const container = document.getElementById("job-keywords-list");
  container.textContent = "";
  document.getElementById("job-keywords-error").hidden = true;

  // Two groups of cards under their own headings; each card keeps its place in keywordTerms (data-index), so "Save my choices" is unchanged.
  const section = (heading, note, items) => {
    const box = document.createElement("div");
    box.className = "evidence-group";
    if (items.length) {
      const h = document.createElement("h5");
      h.className = "evidence-group-heading";
      h.textContent = heading + " (" + items.length + ")";
      box.appendChild(h);
      const p = document.createElement("p");
      p.className = "hint";
      p.textContent = note;
      box.appendChild(p);
      container.appendChild(box);
    }
    return box;
  };
  const questionBox = section("One question each", "Your profile is close, or the posting accepts several options, but it does not say exactly what you did. Skip is fine: skipping is never treated as “no”.", groups.questions);
  const gapBox = section("Not evidenced yet", "Nothing in your profile says this. If it is true, tell us; otherwise it stays off your resume.", groups.notEvidenced);
  const chipKind = new Map(groups.questions.map((g) => [g.index, "question"]).concat(groups.notEvidenced.map((g) => [g.index, "none"])));

  keywordTerms.forEach((t, i) => {
    const card = document.createElement("div");
    card.className = "question-card";
    card.dataset.index = String(i);

    const title = document.createElement("p");
    title.textContent = t.term + (t.importance && t.importance !== "mentioned" ? " (" + t.importance + ")" : "");
    title.style.fontWeight = "600";
    title.appendChild(document.createTextNode(" "));
    title.appendChild(evidenceChip(chipKind.get(i)));
    card.appendChild(title);

    const why = document.createElement("p");
    why.className = "hint";
    why.style.fontWeight = "400";
    why.textContent = t.support === "related" && t.evidence
      ? "Your profile suggests this: " + t.evidence
      : "Nothing in your profile mentions this yet.";
    card.appendChild(why);

    if (t.alternatives) {
      // The posting accepts any ONE of these: one question, and the candidate names the one that is actually true for them.
      const note = document.createElement("p");
      note.className = "hint";
      note.style.fontWeight = "400";
      note.textContent = "The posting accepts any one of these" + (t.accepts_equivalent_experience ? " (or equivalent experience)" : "") +
        ". Only pick one you really hold; we never claim a certification you don’t have.";
      card.appendChild(note);
      const whichLabel = document.createElement("label");
      whichLabel.className = "field";
      whichLabel.innerHTML = "<span>Which one is true for you?</span>";
      const which = document.createElement("select");
      which.className = "keyword-which";
      const choose = document.createElement("option");
      choose.value = "";
      choose.textContent = "Choose one";
      which.appendChild(choose);
      t.alternatives.forEach((name) => {
        const opt = document.createElement("option");
        opt.value = name;
        opt.textContent = name;
        which.appendChild(opt);
      });
      whichLabel.appendChild(which);
      card.appendChild(whichLabel);
    }

    const select = document.createElement("select");
    select.className = "keyword-action";
    [
      ["skip", "Skip — not me / not now"],
      ["skill", "Yes — save to my Skills (used on every resume)"],
      ["resume", "Yes — use on this resume only"],
    ].forEach(([value, label]) => {
      const opt = document.createElement("option");
      opt.value = value;
      opt.textContent = label;
      select.appendChild(opt);
    });
    // Always starts on Skip: nothing is saved to the profile unless the candidate picks it.
    select.value = "skip";
    card.appendChild(select);

    const extra = document.createElement("div");
    extra.className = "keyword-extra";

    const roleLabel = document.createElement("label");
    roleLabel.className = "field keyword-role-field";
    roleLabel.innerHTML = "<span>Which role did this come from? (optional)</span>";
    const roleSelect = document.createElement("select");
    roleSelect.className = "keyword-role";
    const none = document.createElement("option");
    none.value = "";
    none.textContent = "Not tied to one role";
    roleSelect.appendChild(none);
    (typeof allExperiences !== "undefined" ? allExperiences : []).forEach((e) => {
      const opt = document.createElement("option");
      opt.value = String(e.id);
      opt.textContent = e.title + " — " + e.organization;
      roleSelect.appendChild(opt);
    });
    roleLabel.appendChild(roleSelect);
    extra.appendChild(roleLabel);

    const sentenceLabel = document.createElement("label");
    sentenceLabel.className = "field";
    sentenceLabel.innerHTML = "<span>How you did it, in a specific sentence (optional). &ldquo;Balanced an open cash drawer for 5 years&rdquo; says more than &ldquo;cashier&rdquo;. It is never printed in the Skills list.</span>";
    const sentence = document.createElement("textarea");
    sentence.className = "keyword-sentence";
    sentence.rows = 2;
    sentenceLabel.appendChild(sentence);
    extra.appendChild(sentenceLabel);
    card.appendChild(extra);

    const sync = () => {
      extra.hidden = select.value === "skip";
      roleLabel.hidden = select.value !== "skill";
    };
    select.addEventListener("change", sync);
    sync();

    (chipKind.get(i) === "question" ? questionBox : gapBox).appendChild(card);
  });
}

document.getElementById("job-keywords-back-btn").addEventListener("click", () => {
  showJobBuildForm();
  jobStepDone("Keyword choices not saved. " + JOB_BUILD_FORM_MESSAGE);
});

document.getElementById("job-keywords-apply-btn").addEventListener("click", async () => {
  const errorEl = document.getElementById("job-keywords-error");
  errorEl.hidden = true;
  const btn = document.getElementById("job-keywords-apply-btn");
  btn.disabled = true;

  // Choices from an earlier pass are replaced, not stacked.
  jobState.discoveredFacts = jobState.discoveredFacts.filter((f) => f.source !== "keyword_check");
  let savedSkills = 0;
  let resumeOnly = 0;
  try {
    const cards = document.querySelectorAll("#job-keywords-list .question-card");
    for (const card of cards) {
      const t = keywordTerms[Number(card.dataset.index)];
      const action = card.querySelector(".keyword-action").value;
      if (action === "skip") continue;
      const sentence = card.querySelector(".keyword-sentence").value.trim();
      const whichEl = card.querySelector(".keyword-which");
      const term = whichEl ? whichEl.value : t.term; // a group card saves only the alternative the candidate chose
      if (!term) throw new Error(`Choose which one is true for you for "${t.term}", or set it to Skip.`);

      if (action === "skill") {
        const role = card.querySelector(".keyword-role").value;
        const res = await authedFetch("/api/career/skills", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ name: term, source_text: sentence || null, experience_id: role ? Number(role) : null }),
        });
        if (!res.ok) {
          const err = await res.json().catch(() => ({}));
          throw new Error(formatErrorDetail(err.detail, `Couldn’t save "${term}" (${res.status})`));
        }
        savedSkills += 1;
        // Saved: flip the card to Skip so a retry after a later error can't save it twice.
        const actionSelect = card.querySelector(".keyword-action");
        actionSelect.value = "skip";
        actionSelect.dispatchEvent(new Event("change"));
      } else {
        jobState.discoveredFacts.push({
          category: term,
          bullet_text: sentence || "Has real hands-on experience with " + term + ".",
          source: "keyword_check",
        });
        resumeOnly += 1;
      }
    }
  } catch (err) {
    errorEl.textContent = err.message + (savedSkills ? " (" + savedSkills + " were already saved and are now set to Skip. Press Save again to finish the rest.)" : "");
    errorEl.hidden = false;
    btn.disabled = false;
    focusJob(btn); // a disabled button loses focus; give it back
    return;
  }

  if (savedSkills && typeof loadSkills === "function") await loadSkills();
  btn.disabled = false;
  showJobBuildForm();
  const parts = [];
  if (savedSkills) parts.push(savedSkills + " saved to your Skills");
  if (resumeOnly) parts.push(resumeOnly + " added for this resume only");
  showKeywordNote(parts.length ? "Keyword choices: " + parts.join(", ") + ". Now build your resume." : "No keywords added.");
  focusJob(jobHeading);
});

// Opens the Add a skill form with the posting term filled in, so a skill the
// candidate really has (but never wrote down) becomes part of the profile and
// is used in every later resume.
function prefillSkillFromTerm(term) {
  revealCareerProfileSections("career-profile-editor");
  document.getElementById("mode-manual-btn").click();
  document.getElementById("skill-name").value = term;
  document.getElementById("skill-source-text").focus();
}

// "Still worth addressing": posting terms the profile does not support yet
// (required ones first), plus any that are supported but could not be placed.
function renderTermReport(report) {
  // Context wording the builder chose not to use is neutral: not a problem, not counted.
  // An unmet member of an alternatives group that another member already meets is counted as "met through another accepted option"
  // in the summary but is not a gap, so it is left out of the lists below and of the match grade.
  const groups = groupReport(report);
  report = report.filter((r) => r.status !== "wording_unused" && r.status !== "alternative_met");
  const block = document.getElementById("job-term-report-block");
  const summary = document.getElementById("job-term-summary");
  const missingList = document.getElementById("job-term-missing-list");
  const includedList = document.getElementById("job-term-included-list");
  const includedDetails = document.getElementById("job-term-included-details");
  missingList.textContent = "";
  includedList.textContent = "";
  block.hidden = groups.total === 0;
  renderEvidenceTiles(document.getElementById("job-term-tiles"), groups.tiles);
  if (report.length === 0) {
    summary.textContent = "";
    return;
  }

  const rank = { required: 0, preferred: 1, mentioned: 2 };
  const byRank = (a, b) => (rank[a.importance] ?? 3) - (rank[b.importance] ?? 3);
  const onResume = report.filter((r) => r.status === "on_resume");
  const notPlaced = report.filter((r) => r.status === "not_placed").sort(byRank);
  const notInProfile = report.filter((r) => r.status === "not_in_profile").sort(byRank);
  // Real experience that is different from what the posting names: shown as relevant, never claimed as the posting's own wording.
  const transferable = report.filter((r) => r.status === "transferable").sort(byRank);

  let text = onResume.length + " of " + report.length + " terms from the posting are on your resume.";
  if (notInProfile.length) text += " " + notInProfile.length + (notInProfile.length === 1 ? " isn’t" : " aren’t") + " backed by your profile yet. If you have that experience, add it and rebuild.";
  if (transferable.length) text += " " + transferable.length + (transferable.length === 1 ? " more is" : " more are") + " related to experience you already have, so you may be able to build on " + (transferable.length === 1 ? "it" : "them") + ".";
  if (notPlaced.length) text += " " + notPlaced.length + (notPlaced.length === 1 ? " is" : " are") + " in your profile but couldn’t be placed, so add " + (notPlaced.length === 1 ? "it" : "them") + " by hand.";
  summary.textContent = text;

  for (const item of notPlaced.concat(notInProfile, transferable)) {
    const li = document.createElement("li");
    const label = item.term + (item.importance && item.importance !== "mentioned" ? " (" + item.importance + ")" : "");
    li.textContent = label + " ";
    li.appendChild(evidenceChip(item.status === "not_placed" ? "profile" : item.status === "transferable" ? "question" : "none"));
    li.appendChild(document.createTextNode(item.status === "not_placed" ? " — in your profile, but couldn’t be placed on the resume " : item.status === "transferable" ? " — your experience may be relevant" + (item.evidence ? ": " + item.evidence : "") : " "));
    if (item.status === "not_in_profile") {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "entry-remove-btn";
      btn.textContent = "I have this — add to my profile";
      btn.addEventListener("click", () => prefillSkillFromTerm(item.term));
      li.appendChild(btn);
    }
    missingList.appendChild(li);
  }

  includedDetails.hidden = onResume.length === 0;
  const summaryEl = includedDetails.querySelector("summary");
  if (summaryEl) summaryEl.textContent = "On your resume (" + onResume.length + "): terms from the posting";
  for (const item of onResume.slice().sort(byRank)) {
    // A chip per term (required ones first); the evidence is on hover.
    const li = document.createElement("li");
    li.textContent = item.term;
    if (item.importance === "required") li.classList.add("term-chip-required");
    if (item.evidence) li.title = item.evidence;
    includedList.appendChild(li);
  }
}

// Editable suggestions (no AI): the candidate's OWN saved sentence about a supported term that could not be placed, offered as a new bullet
// under its role on this resume. They edit it, see the before and after, and add it to this resume only; nothing changes until they do, and
// "Undo" puts the resume back as it was built. Their saved roles and skills are never touched.
function suggestionsEls() {
  return {
    block: document.getElementById("job-suggestions-block"),
    list: document.getElementById("job-suggestions-list"),
    status: document.getElementById("job-suggestions-status"),
    undo: document.getElementById("job-suggestions-undo-btn"),
  };
}

function clearSuggestions() {
  const els = suggestionsEls();
  els.block.hidden = true;
  els.list.textContent = "";
  els.status.textContent = "";
  els.undo.hidden = true;
}

async function loadSuggestions(message) {
  clearSuggestions();
  const id = jobState.resumeVersionId;
  if (!id) return;
  let data;
  try {
    const res = await authedFetch("/api/career/resume-versions/" + id + "/suggestions");
    if (!res.ok) return; // suggestions are optional: a failure leaves the resume exactly as built
    data = await res.json();
  } catch (err) {
    return;
  }
  renderSuggestions(data.suggestions || [], data.applied || [], message);
}

function renderSuggestions(items, applied, message) {
  const els = suggestionsEls();
  els.list.textContent = "";
  els.undo.hidden = applied.length === 0;
  els.block.hidden = items.length === 0 && applied.length === 0;
  els.status.textContent = message || (applied.length ? applied.length + (applied.length === 1 ? " bullet was" : " bullets were") + " added from your suggestions." : "");
  items.forEach((s) => els.list.appendChild(suggestionCard(s)));
}

function suggestionCard(s) {
  const card = document.createElement("div");
  card.className = "question-card suggestion-card";

  const title = document.createElement("p");
  title.style.fontWeight = "600";
  title.textContent = s.term + (s.importance && s.importance !== "mentioned" ? " (" + s.importance + ")" : "");
  card.appendChild(title);

  const source = document.createElement("p");
  source.className = "hint";
  source.textContent = "From your " + s.role + (s.organization ? " role at " + s.organization : " role") + ": “" + s.source_sentence + "”";
  card.appendChild(source);

  const label = document.createElement("label");
  label.className = "field";
  label.innerHTML = "<span>Wording to add (you can edit it)</span>";
  const text = document.createElement("textarea");
  text.className = "suggestion-text";
  text.rows = 2;
  text.value = s.suggested_text;
  label.appendChild(text);
  card.appendChild(label);

  const preview = document.createElement("details");
  preview.open = true;
  preview.className = "suggestion-preview";
  const summary = document.createElement("summary");
  summary.textContent = "Before and after, under " + s.role;
  preview.appendChild(summary);
  const grid = document.createElement("div");
  grid.className = "suggestion-compare";
  const column = (heading) => {
    const box = document.createElement("div");
    const h = document.createElement("p");
    h.className = "suggestion-compare-head";
    h.textContent = heading;
    const ul = document.createElement("ul");
    box.appendChild(h);
    box.appendChild(ul);
    grid.appendChild(box);
    return ul;
  };
  const beforeList = column("Before");
  const afterList = column("After (1 change)");
  (s.before_bullets.length ? s.before_bullets : ["(no bullets under this role yet)"]).forEach((b) => {
    beforeList.appendChild(Object.assign(document.createElement("li"), { textContent: b }));
    afterList.appendChild(Object.assign(document.createElement("li"), { textContent: b }));
  });
  const added = document.createElement("li");
  added.className = "suggestion-new";
  added.textContent = text.value;
  afterList.appendChild(added);
  text.addEventListener("input", () => { added.textContent = text.value; });
  preview.appendChild(grid);
  card.appendChild(preview);

  const error = document.createElement("p");
  error.className = "error-message";
  error.setAttribute("role", "alert");
  error.hidden = true;
  card.appendChild(error);

  const actions = document.createElement("div");
  actions.className = "suggestion-actions";
  const add = document.createElement("button");
  add.type = "button";
  add.className = "btn-primary";
  add.textContent = "Add to this resume";
  const skip = document.createElement("button");
  skip.type = "button";
  skip.className = "btn-secondary";
  skip.textContent = "Not for this resume";
  actions.appendChild(add);
  actions.appendChild(skip);
  card.appendChild(actions);

  skip.addEventListener("click", () => {
    card.remove();
    const els = suggestionsEls();
    els.status.textContent = "Left “" + s.term + "” off. Nothing was changed.";
    els.block.hidden = els.list.children.length === 0 && els.undo.hidden;
  });
  add.addEventListener("click", async () => {
    error.hidden = true;
    add.disabled = true;
    try {
      const res = await authedFetch("/api/career/resume-versions/" + jobState.resumeVersionId + "/suggestions/apply", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ choices: [{ term: s.term, experience_index: s.experience_index, text: text.value.trim() }] }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(formatErrorDetail(err.detail, "Couldn’t add that wording (" + res.status + ")."));
      }
      const data = await res.json();
      jobState.tailoredResumeData = data.resume_data;
      renderTermReport(data.resume_data.term_report || []);
      await loadSuggestions("Added “" + s.term + "” wording under " + s.role + ". Your saved roles and skills were not changed.");
      announceJob("Added to this resume.");
    } catch (err) {
      error.textContent = err.message || "Couldn’t add that wording.";
      error.hidden = false;
      add.disabled = false;
      focusJob(add);
    }
  });
  return card;
}

document.getElementById("job-suggestions-undo-btn").addEventListener("click", async () => {
  const btn = document.getElementById("job-suggestions-undo-btn");
  btn.disabled = true;
  try {
    const res = await authedFetch("/api/career/resume-versions/" + jobState.resumeVersionId + "/suggestions/undo", { method: "POST" });
    if (!res.ok) throw new Error("Couldn’t undo that (" + res.status + ").");
    const data = await res.json();
    jobState.tailoredResumeData = data.resume_data;
    renderTermReport(data.resume_data.term_report || []);
    await loadSuggestions("Undone: your resume is back as it was built.");
    announceJob("Undone.");
  } catch (err) {
    suggestionsEls().status.textContent = err.message || "Couldn’t undo that.";
  } finally {
    btn.disabled = false;
  }
});

// A rough letter grade for how much of the posting's key terms are on the
// resume - deliberately a band, not a precise score. Required terms count
// 3x, preferred 2x, others 1x. Terms the profile can't honestly support
// count as misses (that's the point: they should stay off the resume).
const MATCH_GRADES = [
  { min: 90, letter: "A", band: "90%+", title: "Strong match", text: "Nearly every key term in the posting is on your resume." },
  { min: 80, letter: "B", band: "80–89%", title: "Good match", text: "Most key terms are on your resume. A few are missing; see below." },
  { min: 70, letter: "C", band: "70–79%", title: "Fair match", text: "Many key terms are on your resume, but several the posting asks for are not." },
  { min: 0, letter: "D", band: "under 70%", title: "Weak match", text: "A lot of what the posting asks for isn’t on this resume yet. Check the list below for terms you can honestly add." },
];

function computeMatchGrade(report) {
  const weight = { required: 3, preferred: 2, mentioned: 1 };
  let got = 0;
  let total = 0;
  for (const r of report) {
    if (r.status === "wording_unused" || r.status === "alternative_met") continue;
    const w = weight[r.importance] ?? 1;
    total += w;
    if (r.status === "on_resume") got += w;
  }
  if (total === 0) return null;
  const pct = Math.round((got / total) * 100);
  return { pct, ...MATCH_GRADES.find((g) => pct >= g.min) };
}

function renderMatchGrade(report, ats) {
  const block = document.getElementById("job-match-grade-block");
  const grade = report && report.length ? computeMatchGrade(report) : null;
  block.hidden = !grade;
  block.className = "match-grade" + (grade ? " match-grade-" + grade.letter.toLowerCase() : "");
  if (!grade) return;
  document.getElementById("job-match-grade-letter").textContent = grade.letter;
  document.getElementById("job-match-grade-title").textContent = grade.title + " (" + grade.band + " of key terms)";
  document.getElementById("job-match-grade-explain").textContent = grade.text;
  // The scanner-style number: every posting term counts equally, including ones your profile doesn't support.
  const atsLine = document.getElementById("job-ats-line");
  atsLine.hidden = !(ats && ats.total);
  if (ats && ats.total) {
    atsLine.textContent = "ATS-style score: " + ats.pct + "% (" + ats.found + " of " + ats.total + " posting terms appear on this resume). Outside scanners such as Jobscan count every term the posting uses, even ones you can’t honestly claim, so this is the number to compare with them.";
  }
  document.getElementById("job-match-grade-note").textContent =
    "Based on the key terms we found in this posting and what your profile honestly supports. Other scoring tools may pick different terms, and terms you don’t have should stay off.";
}

// Shows which roles kept their full bullets and which were shortened to one
// line, so the candidate can tell if the builder guessed relevance wrong.
function renderRoleSelection(selection) {
  const block = document.getElementById("job-role-selection-block");
  const list = document.getElementById("job-role-selection-list");
  list.textContent = "";
  block.hidden = selection.length === 0;
  for (const item of selection) {
    const li = document.createElement("li");
    const label = item.treatment === "omitted" ? "left off" : "kept with key bullets";
    li.textContent = (item.title || "") + (item.organization ? " — " + item.organization : "") + ": " + label + (item.reason ? " (" + item.reason + ")" : "");
    list.appendChild(li);
  }
}

// "I applied for this job": the app can't know the candidate applied, so this is
// their own one-click entry into the application tracker (applications.js).
// One line when the truth checks left statements out of the resume; the wording and the count come from the server.
// Lines held back for the candidate's confirmation are listed word for word, so nothing the candidate said is lost, and they are not
// shown as verified.
function renderTruthNotice(notice) {
  const el = document.getElementById("job-truth-notice");
  if (!el) return;
  const message = notice && notice.count > 0 && typeof notice.message === "string" ? notice.message : "";
  const held = notice && Array.isArray(notice.held) ? notice.held.filter((h) => h && typeof h.text === "string" && h.text) : [];
  const heldMessage = held.length && typeof notice.held_message === "string" ? notice.held_message : "";
  const show = (id, text) => {
    const node = document.getElementById(id);
    if (node) { node.textContent = text; node.hidden = !text; }
  };
  show("job-truth-message", message);
  show("job-truth-held-message", heldMessage);
  const restoredMessage = notice && typeof notice.restored_message === "string" ? notice.restored_message : "";
  show("job-truth-restored-message", restoredMessage);
  const list = document.getElementById("job-truth-held");
  if (list) {
    list.textContent = "";
    if (heldMessage) {
      for (const h of held) {
        const li = document.createElement("li");
        li.textContent = h.said ? h.text + " (you wrote: “" + h.said + "”)" : h.text;
        list.appendChild(li);
      }
    }
    list.hidden = !heldMessage;
  }
  // What the provenance check changed: lines put back to the candidate's own words for that role, or left out, and why.
  const prov = notice && notice.provenance && notice.provenance.count > 0 ? notice.provenance : null;
  const provMessage = prov && typeof prov.message === "string" ? prov.message : "";
  show("job-truth-provenance-message", provMessage);
  const provList = document.getElementById("job-truth-provenance");
  if (provList) {
    provList.textContent = "";
    if (provMessage) {
      for (const item of Array.isArray(prov.items) ? prov.items : []) {
        const li = document.createElement("li");
        li.textContent = "“" + item.text + "”: " + item.change + " (" + item.why + ")";
        provList.appendChild(li);
      }
    }
    provList.hidden = !provMessage;
  }
  el.hidden = !(message || heldMessage || restoredMessage || provMessage);
}

function resetAppliedBlock() {
  document.getElementById("job-applied-form").hidden = true;
  document.getElementById("job-applied-msg").hidden = true;
  const btn = document.getElementById("job-applied-btn");
  btn.disabled = false;
  btn.hidden = false;
}

document.getElementById("job-applied-btn").addEventListener("click", (event) => {
  const fromKeyboard = jobKeyboardPress(event); // read before this button is hidden below
  // The comparison's label is usually "Job Title at Company": split it as a starting point.
  const label = jobState.jobTitle || "";
  const at = label.lastIndexOf(" at ");
  document.getElementById("job-applied-title").value = at > 0 ? label.slice(0, at) : label;
  document.getElementById("job-applied-company").value = at > 0 ? label.slice(at + 4) : "";
  document.getElementById("job-applied-date").value = todayIso();
  document.getElementById("job-applied-form").hidden = false;
  document.getElementById("job-applied-btn").hidden = true;
  if (fromKeyboard) focusJob(document.getElementById("job-applied-title"));
});

document.getElementById("job-applied-cancel-btn").addEventListener("click", () => {
  resetAppliedBlock();
  focusJob(document.getElementById("job-applied-btn"));
});

document.getElementById("job-applied-save-btn").addEventListener("click", async () => {
  const msg = document.getElementById("job-applied-msg");
  const saveBtn = document.getElementById("job-applied-save-btn");
  saveBtn.disabled = true;
  try {
    if (jobState.opportunityId) {
      // C-52: a comparison started from a saved link is recorded through that link, which checks the approved résumé.
      await recordSavedJobApplication(jobState.opportunityId, document.getElementById("job-applied-date").value || null);
      document.getElementById("job-applied-form").hidden = true;
      msg.textContent = "Recorded for this saved job. It is now in your tracker, and you can add a follow-up date on the saved link.";
    } else {
      await addApplication({
        job_title: document.getElementById("job-applied-title").value,
        company: document.getElementById("job-applied-company").value,
        applied_on: document.getElementById("job-applied-date").value || null,
        scan_history_id: jobState.scanHistoryId,
        resume_version_id: jobState.resumeVersionId,
      });
      document.getElementById("job-applied-form").hidden = true;
      msg.textContent = "Added to your tracker. Find it under Applications in your Career Snapshot, and update it when you hear back.";
    }
  } catch (err) {
    msg.textContent = err.message || "Couldn’t add that application.";
  } finally {
    msg.hidden = false;
    saveBtn.disabled = false;
    focusJob(msg); // the saved or failed message is read when it gets focus; the form is still below it after a failure
  }
});

document.getElementById("job-download-btn").addEventListener("click", async () => {
  const button = document.getElementById("job-download-btn");
  const messageEl = document.getElementById("job-download-msg");
  clearResumeDownloadMessage(messageEl);
  if (!jobState.tailoredResumeData) {
    showResumeDownloadMessage(messageEl, RESUME_NOT_READY_MESSAGE);
    return;
  }
  button.disabled = true;
  try {
    const res = await authedFetch("/api/generate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ resume_data: jobState.tailoredResumeData, ats_mode: false, template: document.getElementById("job-resume-template").value }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(formatErrorDetail(err.detail, `Request failed (${res.status})`));
    }
    saveResumeBlob(await res.blob(), resumeFileName(jobState.tailoredResumeData.name, jobState.jobTitle));
  } catch (err) {
    // the message sits under the button; nothing on the page is cleared, so the same button can simply be pressed again
    showResumeDownloadMessage(messageEl, resumeDownloadErrorText(err));
  } finally {
    button.disabled = false;
  }
});

function resetJobTarget() {
  jobState.jobDescription = "";
  jobState.categories = [];
  jobState.history = [];
  jobState.roundNumber = 1;
  jobState.discoveredFacts = [];
  jobState.matchReport = null;
  jobState.tailoredResumeData = null;
  jobState.scanHistoryId = null;
  jobState.jobFit = null;
  jobState.jobTitle = "";
  jobState.resumeVersionId = null;
  clearOpportunityContext();
  resetAppliedBlock();
  renderJobFit(null);
  document.getElementById("job-fit-after").hidden = true;
  renderRoleSelection([]);
  renderTermReport([]);
  clearSuggestions();
  renderMatchGrade([]);
  showKeywordNote("");
  keywordTerms = [];
  document.getElementById("job-description-input").value = "";
  document.getElementById("job-build-name").value = "";
  document.getElementById("job-build-contact").value = "";
  hideAllJobStates();
  document.getElementById("job-skipped-note").hidden = true;
  jobTargetEmpty.hidden = false;
  announceJob("");
  focusJob(document.getElementById("job-target-add-btn"));
}

document.getElementById("job-start-over-btn").addEventListener("click", resetJobTarget);
document.getElementById("job-match-new-btn").addEventListener("click", resetJobTarget);

// "Skip this job": mark the saved comparison as skipped (it stays under Skipped jobs in the "See your progress" card and can be brought back), then go
// back to the empty Current Job Target, so it no longer shows up as "Continue" or as an unfinished resume.
document.getElementById("job-skip-job-btn").addEventListener("click", async () => {
  const btn = document.getElementById("job-skip-job-btn");
  const errorEl = document.getElementById("job-skip-error");
  errorEl.hidden = true;
  const id = jobState.scanHistoryId;
  const title = jobState.jobTitle;
  btn.disabled = true;
  try {
    if (id) {
      const res = await authedFetch("/api/career/scan-history/" + id + "/skip", { method: "POST" });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(formatErrorDetail(err.detail, `Couldn’t skip this job (${res.status})`));
      }
    }
    resetJobTarget();
    if (typeof loadScanHistory === "function") await loadScanHistory();
    restoreCurrentJobTarget();
    const note = document.getElementById("job-skipped-note");
    note.textContent = "Skipped" + (title ? " \u201c" + title + "\u201d" : "") + ". You’ll find it under Skipped jobs lower on this page if you change your mind.";
    note.hidden = false;
    announceJob(note.textContent);
  } catch (err) {
    errorEl.textContent = err.message || "Something went wrong. Please try again.";
    errorEl.hidden = false;
    focusJob(btn);
  } finally {
    btn.disabled = false;
  }
});

// Restores the dashboard's "Current Job Target" to the most recent real
// job comparison on page load, instead of always starting back at the
// empty "+ Add a job" state - the comparison itself was already saved to
// scan history the moment it ran, so the dashboard should reflect that
// rather than pretending it never happened. Reads allScanHistory, a
// shared global populated by history.js's loadScanHistory() (loaded
// before this file), rather than fetching it again here.
function restoreCurrentJobTarget() {
  // The dashboard opens clean. The last comparison is kept, one click away,
  // instead of taking over the page on every refresh.
  const btn = document.getElementById("job-resume-last-btn");
  const latest = (typeof allScanHistory !== "undefined" ? allScanHistory : []).find((s) => s.scan_type === "job_comparison" && !(s.result_data && s.result_data.skipped));
  if (!latest || !latest.result_data || !latest.result_data.match_report) {
    btn.hidden = true;
    return;
  }
  // The button says "Continue comparison" (short, and it cannot be mistaken for the application tracker). The job it reopens is still
  // named for screen readers (aria-label, which starts with the visible words) and on hover (title).
  btn.textContent = "Continue comparison";
  btn.setAttribute("aria-label", latest.job_title ? "Continue comparison: " + latest.job_title : "Continue comparison");
  btn.title = latest.job_title || "";
  btn.onclick = () => openJobTarget(latest);
  btn.hidden = false;
}

// Saved-link handoff (C-52). The posting text is pasted by the member: this app never fetches a saved link.
// The saved link only supplies the context shown above the paste box and the link that the resume approval is recorded on.
function startJobFromOpportunity(item) {
  if (!item || !item.id) return;
  // Start clean: nothing from a previous comparison (pasted posting, match, build, approval) may carry over.
  resetJobTarget();
  jobState.opportunityId = item.id;
  const ctx = document.getElementById("job-opportunity-context");
  ctx.textContent = "Comparing for your saved link: " + item.title + (item.employer ? " at " + item.employer : "") +
    ". Paste the job description from the employer’s page below.";
  ctx.hidden = false;
  hideAllJobStates();
  jobTargetEmpty.hidden = true;
  jobInputState.hidden = false;
  document.getElementById("job-description-input").focus();
  jobStepStarted(jobInputState);
}

function clearOpportunityContext() {
  jobState.opportunityId = null;
  const ctx = document.getElementById("job-opportunity-context");
  if (ctx) { ctx.textContent = ""; ctx.hidden = true; }
  const box = document.getElementById("job-opportunity-approval");
  if (box) box.hidden = true;
  const status = document.getElementById("job-opportunity-approval-status");
  if (status) status.textContent = "";
}

function showOpportunityApproval() {
  const box = document.getElementById("job-opportunity-approval");
  if (!box) return;
  box.hidden = !(jobState.opportunityId && jobState.resumeVersionId);
  document.getElementById("job-opportunity-approval-status").textContent = "";
}

document.getElementById("job-opportunity-approve-btn").addEventListener("click", async () => {
  const status = document.getElementById("job-opportunity-approval-status");
  status.textContent = "Saving the approval...";
  const message = await approveOpportunityResume(jobState.opportunityId, jobState.resumeVersionId);
  status.textContent = message;
});

// Records the application for a saved job through the saved-link route. The server refuses it unless a résumé is approved
// for that job and the approval is still current; the check here only gives a clearer message earlier.
async function recordSavedJobApplication(opportunityId, appliedOn) {
  const items = typeof allOpportunities !== "undefined" ? allOpportunities : [];
  const item = items.find((o) => o.id === opportunityId);
  if (item && (!item.approval || item.approval.status !== "current")) {
    throw new Error("Approve the résumé for this saved job before you record the application.");
  }
  const res = await authedFetch("/api/career/opportunities/" + opportunityId + "/record-application", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ applied_on: appliedOn }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(formatErrorDetail(err.detail, "The application was not recorded."));
  }
  const data = await res.json();
  if (typeof allOpportunities !== "undefined" && data.opportunity) {
    allOpportunities = allOpportunities.map((o) => (o.id === opportunityId ? data.opportunity : o));
    if (typeof renderOpportunities === "function") renderOpportunities();
  }
  return data;
}

function openJobTarget(latest) {
  clearOpportunityContext();
  const data = latest.result_data;
  if (data.opportunity_id) {
    // The comparison was started from a saved link: keep that link for approval and for recording the application.
    const items = typeof allOpportunities !== "undefined" ? allOpportunities : [];
    const linked = items.find((o) => o.id === data.opportunity_id);
    jobState.opportunityId = data.opportunity_id;
    const ctx = document.getElementById("job-opportunity-context");
    ctx.textContent = "Comparing for your saved link" + (linked ? ": " + linked.title + (linked.employer ? " at " + linked.employer : "") : "") + ".";
    ctx.hidden = false;
  }
  jobState.jobDescription = data.job_description || "";
  jobState.matchReport = data.match_report;
  jobState.categories = data.categories || [];
  jobState.history = data.qa_history || [];
  jobState.roundNumber = 1;
  jobState.discoveredFacts = [];
  jobState.scanHistoryId = latest.id;
  currentJobQuestions = data.questions || [];

  renderJobMatch(jobState.matchReport);
  jobState.jobFit = data.job_fit || null;
  jobState.jobTitle = latest.job_title || data.job_title || "";
  renderJobFit(jobState.jobFit);
  hideAllJobStates();
  jobMatchState.hidden = false;
  jobStepDone("Job comparison ready.");
}
