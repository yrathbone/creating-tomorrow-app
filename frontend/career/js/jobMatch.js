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
  } catch (err) {
    stopProcessingState(jobLoadingState);
    hideAllJobStates();
    jobInputState.hidden = false;
    errorEl.textContent = err.message || "Something went wrong. Please try again.";
    errorEl.hidden = false;
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
      throw new Error(formatErrorDetail(err.detail, `Request failed (${res.status})`));
    }
    const data = await res.json();

    stopProcessingState(jobLoadingState);
    jobLoadingState.hidden = true;

    if (data.stage === "confirm") {
      jobState.discoveredFacts = data.discovered_facts || [];
      await refreshJobFit();
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
  prefillResumeHeader(document.getElementById("job-build-name"), document.getElementById("job-build-contact"));
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
  startProcessingState(jobBuildLoadingState, [
    "Reading the posting's key terms...",
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
    renderMatchGrade(data.term_report || []);

    stopProcessingState(jobBuildLoadingState);
    jobBuildLoadingState.hidden = true;
    jobBuildDoneState.hidden = false;
    carryLayoutChoice("job-build-layout", "job-resume-template");
    if (typeof loadScanHistory === "function") loadScanHistory();
    if (typeof loadResumeVersions === "function") loadResumeVersions();
  } catch (err) {
    stopProcessingState(jobBuildLoadingState);
    hideAllJobStates();
    jobBuildFormState.hidden = false;
    errorEl.textContent = err.message || "Something went wrong building your resume.";
    errorEl.hidden = false;
  }
});

// Optional keyword check before building: posting terms that are not in the
// profile yet, each with the candidate's own choice - save it as a Skill
// (optionally under a role, with a sentence on how it was used), use it for
// this resume only, or skip. Nothing is saved until "Save my choices", and
// nothing is assumed: "related" terms are only pre-selected as a suggestion.
let keywordTerms = [];

document.getElementById("job-keyword-check-btn").addEventListener("click", async () => {
  const errorEl = document.getElementById("job-build-error");
  errorEl.hidden = true;

  hideAllJobStates();
  jobLoadingState.hidden = false;
  startProcessingState(jobLoadingState, [
    "Reading the posting's key terms...",
    "Checking them against your profile...",
  ]);

  try {
    const res = await authedFetch("/api/career/job-keyword-check", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ job_description: jobState.jobDescription, confirmed_facts: jobState.discoveredFacts }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(formatErrorDetail(err.detail, `Request failed (${res.status})`));
    }
    const data = await res.json();
    keywordTerms = data.terms || [];

    stopProcessingState(jobLoadingState);
    jobLoadingState.hidden = true;
    if (keywordTerms.length === 0) {
      showJobBuildForm();
      showKeywordNote("Every key term in the posting is already backed by your profile. Nothing to add.");
      return;
    }
    renderKeywordCards(data.already_covered || 0);
    jobKeywordsState.hidden = false;
  } catch (err) {
    stopProcessingState(jobLoadingState);
    showJobBuildForm();
    errorEl.textContent = err.message || "Something went wrong checking the keywords.";
    errorEl.hidden = false;
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
      errorEl.textContent = formatErrorDetail(err.detail, "Couldn't save that skill.");
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
}

function renderKeywordCards(alreadyCovered) {
  document.getElementById("job-keywords-intro").textContent =
    alreadyCovered + " other key terms are already backed by your profile. For each term below, tell me honestly whether it's true for you. " +
    "Anything you skip stays off your resume.";
  const container = document.getElementById("job-keywords-list");
  container.textContent = "";
  document.getElementById("job-keywords-error").hidden = true;

  keywordTerms.forEach((t, i) => {
    const card = document.createElement("div");
    card.className = "question-card";
    card.dataset.index = String(i);

    const title = document.createElement("p");
    title.textContent = t.term + (t.importance && t.importance !== "mentioned" ? " (" + t.importance + ")" : "");
    title.style.fontWeight = "600";
    card.appendChild(title);

    const why = document.createElement("p");
    why.className = "hint";
    why.style.fontWeight = "400";
    why.textContent = t.support === "related" && t.evidence
      ? "Your profile suggests this: " + t.evidence
      : "Nothing in your profile mentions this yet.";
    card.appendChild(why);

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
    sentenceLabel.innerHTML = "<span>How you did it, in a sentence (optional, never printed in the Skills list)</span>";
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

    container.appendChild(card);
  });
}

document.getElementById("job-keywords-back-btn").addEventListener("click", () => {
  showJobBuildForm();
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

      if (action === "skill") {
        const role = card.querySelector(".keyword-role").value;
        const res = await authedFetch("/api/career/skills", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ name: t.term, source_text: sentence || null, experience_id: role ? Number(role) : null }),
        });
        if (!res.ok) {
          const err = await res.json().catch(() => ({}));
          throw new Error(formatErrorDetail(err.detail, `Couldn't save "${t.term}" (${res.status})`));
        }
        savedSkills += 1;
        // Saved: flip the card to Skip so a retry after a later error can't save it twice.
        const actionSelect = card.querySelector(".keyword-action");
        actionSelect.value = "skip";
        actionSelect.dispatchEvent(new Event("change"));
      } else {
        jobState.discoveredFacts.push({
          category: t.term,
          bullet_text: sentence || "Has real hands-on experience with " + t.term + ".",
          source: "keyword_check",
        });
        resumeOnly += 1;
      }
    }
  } catch (err) {
    errorEl.textContent = err.message + (savedSkills ? " (" + savedSkills + " were already saved and are now set to Skip. Press Save again to finish the rest.)" : "");
    errorEl.hidden = false;
    btn.disabled = false;
    return;
  }

  if (savedSkills && typeof loadSkills === "function") await loadSkills();
  btn.disabled = false;
  showJobBuildForm();
  const parts = [];
  if (savedSkills) parts.push(savedSkills + " saved to your Skills");
  if (resumeOnly) parts.push(resumeOnly + " added for this resume only");
  showKeywordNote(parts.length ? "Keyword choices: " + parts.join(", ") + ". Now build your resume." : "No keywords added.");
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
  report = report.filter((r) => r.status !== "wording_unused");
  const block = document.getElementById("job-term-report-block");
  const summary = document.getElementById("job-term-summary");
  const missingList = document.getElementById("job-term-missing-list");
  const includedList = document.getElementById("job-term-included-list");
  const includedDetails = document.getElementById("job-term-included-details");
  missingList.textContent = "";
  includedList.textContent = "";
  block.hidden = report.length === 0;
  if (report.length === 0) return;

  const rank = { required: 0, preferred: 1, mentioned: 2 };
  const byRank = (a, b) => (rank[a.importance] ?? 3) - (rank[b.importance] ?? 3);
  const onResume = report.filter((r) => r.status === "on_resume");
  const notPlaced = report.filter((r) => r.status === "not_placed").sort(byRank);
  const notInProfile = report.filter((r) => r.status === "not_in_profile").sort(byRank);

  let text = onResume.length + " of " + report.length + " terms from the posting are on your resume.";
  if (notInProfile.length) text += " " + notInProfile.length + " aren't backed by your profile yet. If you have that experience, add it and rebuild.";
  if (notPlaced.length) text += " " + notPlaced.length + (notPlaced.length === 1 ? " is" : " are") + " in your profile but couldn't be placed, so add " + (notPlaced.length === 1 ? "it" : "them") + " by hand.";
  summary.textContent = text;

  for (const item of notPlaced.concat(notInProfile)) {
    const li = document.createElement("li");
    const label = item.term + (item.importance && item.importance !== "mentioned" ? " (" + item.importance + ")" : "");
    li.textContent = label + (item.status === "not_placed" ? " — in your profile, but couldn't be placed on the resume " : " ");
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

// A rough letter grade for how much of the posting's key terms are on the
// resume - deliberately a band, not a precise score. Required terms count
// 3x, preferred 2x, others 1x. Terms the profile can't honestly support
// count as misses (that's the point: they should stay off the resume).
const MATCH_GRADES = [
  { min: 90, letter: "A", band: "90%+", title: "Strong match", text: "Nearly every key term in the posting is on your resume." },
  { min: 80, letter: "B", band: "80–89%", title: "Good match", text: "Most key terms are on your resume. A few are missing; see below." },
  { min: 70, letter: "C", band: "70–79%", title: "Fair match", text: "Many key terms are on your resume, but several the posting asks for are not." },
  { min: 0, letter: "D", band: "under 70%", title: "Weak match", text: "A lot of what the posting asks for isn't on this resume yet. Check the list below for terms you can honestly add." },
];

function computeMatchGrade(report) {
  const weight = { required: 3, preferred: 2, mentioned: 1 };
  let got = 0;
  let total = 0;
  for (const r of report) {
    if (r.status === "wording_unused") continue;
    const w = weight[r.importance] ?? 1;
    total += w;
    if (r.status === "on_resume") got += w;
  }
  if (total === 0) return null;
  const pct = Math.round((got / total) * 100);
  return { pct, ...MATCH_GRADES.find((g) => pct >= g.min) };
}

function renderMatchGrade(report) {
  const block = document.getElementById("job-match-grade-block");
  const grade = report && report.length ? computeMatchGrade(report) : null;
  block.hidden = !grade;
  block.className = "match-grade" + (grade ? " match-grade-" + grade.letter.toLowerCase() : "");
  if (!grade) return;
  document.getElementById("job-match-grade-letter").textContent = grade.letter;
  document.getElementById("job-match-grade-title").textContent = grade.title + " (" + grade.band + " of key terms)";
  document.getElementById("job-match-grade-explain").textContent = grade.text;
  document.getElementById("job-match-grade-note").textContent =
    "Based on the key terms we found in this posting and what your profile honestly supports. Other scoring tools may pick different terms, and terms you don't have should stay off.";
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
function resetAppliedBlock() {
  document.getElementById("job-applied-form").hidden = true;
  document.getElementById("job-applied-msg").hidden = true;
  const btn = document.getElementById("job-applied-btn");
  btn.disabled = false;
  btn.hidden = false;
}

document.getElementById("job-applied-btn").addEventListener("click", () => {
  // The comparison's label is usually "Job Title at Company": split it as a starting point.
  const label = jobState.jobTitle || "";
  const at = label.lastIndexOf(" at ");
  document.getElementById("job-applied-title").value = at > 0 ? label.slice(0, at) : label;
  document.getElementById("job-applied-company").value = at > 0 ? label.slice(at + 4) : "";
  document.getElementById("job-applied-date").value = todayIso();
  document.getElementById("job-applied-form").hidden = false;
  document.getElementById("job-applied-btn").hidden = true;
});

document.getElementById("job-applied-cancel-btn").addEventListener("click", resetAppliedBlock);

document.getElementById("job-applied-save-btn").addEventListener("click", async () => {
  const msg = document.getElementById("job-applied-msg");
  const saveBtn = document.getElementById("job-applied-save-btn");
  saveBtn.disabled = true;
  try {
    await addApplication({
      job_title: document.getElementById("job-applied-title").value,
      company: document.getElementById("job-applied-company").value,
      applied_on: document.getElementById("job-applied-date").value || null,
      scan_history_id: jobState.scanHistoryId,
      resume_version_id: jobState.resumeVersionId,
    });
    document.getElementById("job-applied-form").hidden = true;
    msg.textContent = "Added to your tracker. Find it under Applications in your Career Snapshot, and update it when you hear back.";
  } catch (err) {
    msg.textContent = err.message || "Couldn't add that application.";
  } finally {
    msg.hidden = false;
    saveBtn.disabled = false;
  }
});

document.getElementById("job-download-btn").addEventListener("click", async () => {
  if (!jobState.tailoredResumeData) return;
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
  resetAppliedBlock();
  renderJobFit(null);
  document.getElementById("job-fit-after").hidden = true;
  renderRoleSelection([]);
  renderTermReport([]);
  renderMatchGrade([]);
  showKeywordNote("");
  keywordTerms = [];
  document.getElementById("job-description-input").value = "";
  document.getElementById("job-build-name").value = "";
  document.getElementById("job-build-contact").value = "";
  hideAllJobStates();
  jobTargetEmpty.hidden = false;
}

document.getElementById("job-start-over-btn").addEventListener("click", resetJobTarget);
document.getElementById("job-match-new-btn").addEventListener("click", resetJobTarget);

// Restores the dashboard's "Current Job Target" to the most recent real
// job comparison on page load, instead of always starting back at the
// empty "+ Add a Job" state - the comparison itself was already saved to
// scan history the moment it ran, so the dashboard should reflect that
// rather than pretending it never happened. Reads allScanHistory, a
// shared global populated by history.js's loadScanHistory() (loaded
// before this file), rather than fetching it again here.
function restoreCurrentJobTarget() {
  // The dashboard opens clean. The last comparison is kept, one click away,
  // instead of taking over the page on every refresh.
  const btn = document.getElementById("job-resume-last-btn");
  const latest = (typeof allScanHistory !== "undefined" ? allScanHistory : []).find((s) => s.scan_type === "job_comparison");
  if (!latest || !latest.result_data || !latest.result_data.match_report) {
    btn.hidden = true;
    return;
  }
  btn.textContent = latest.job_title ? "Continue: " + latest.job_title : "Pick up where I left off";
  btn.onclick = () => openJobTarget(latest);
  btn.hidden = false;
}

function openJobTarget(latest) {
  const data = latest.result_data;
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
}
