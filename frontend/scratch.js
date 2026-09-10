// All state lives in this browser tab for this session only - nothing is
// persisted server-side or in local storage (matches the rest of the site:
// "we don't store your information after your session ends").
const state = {
  basics: {},
  experience: [], // { title, subtitle, bullets }
  education: [], // formatted strings
  skills: [],
};

let pendingEntry = null; // { type, title, organization, dates, drafted_bullets, reflective_questions }

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

// --- Step 1: Basics ---------------------------------------------------

// Auto-format a US phone number to XXX-XXX-XXXX once the person finishes
// typing it (on blur, not on every keystroke, so we don't fight their
// cursor position while they're still typing). Leaves anything that isn't
// a clean 10-digit (or 11-digit with a leading 1) number alone rather than
// risk mangling an international number or one with an extension.
function formatPhoneNumber(value) {
  let digits = value.replace(/\D/g, "");
  if (digits.length === 11 && digits[0] === "1") {
    digits = digits.slice(1);
  }
  if (digits.length !== 10) return value;
  return `${digits.slice(0, 3)}-${digits.slice(3, 6)}-${digits.slice(6)}`;
}

document.getElementById("basics-phone").addEventListener("blur", (e) => {
  e.target.value = formatPhoneNumber(e.target.value);
});

document.getElementById("basics-form").addEventListener("submit", (e) => {
  e.preventDefault();
  state.basics = {
    name: document.getElementById("basics-name").value.trim(),
    city: document.getElementById("basics-city").value.trim(),
    state: document.getElementById("basics-state").value.trim(),
    phone: document.getElementById("basics-phone").value.trim(),
    email: document.getElementById("basics-email").value.trim(),
    linkedin: document.getElementById("basics-linkedin").value.trim(),
  };
  goToStep("experience");
});

// --- Step 2: Experience --------------------------------------------------
const entryForm = document.getElementById("entry-form");
const entryError = document.getElementById("entry-error");
const entryLoading = document.getElementById("entry-loading");
const entryReview = document.getElementById("entry-review");
const entryFormWrap = document.getElementById("entry-form-wrap");

entryForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  entryError.hidden = true;

  const entryType = document.getElementById("entry-type").value;
  const title = document.getElementById("entry-title").value.trim();
  const organization = document.getElementById("entry-org").value.trim();
  const location = document.getElementById("entry-location").value.trim();
  const dates = document.getElementById("entry-dates").value.trim();
  const description = document.getElementById("entry-description").value.trim();

  if (!title || !description) {
    showError(entryError, "Please fill in the role and describe what you did.");
    return;
  }

  entryFormWrap.hidden = true;
  entryLoading.hidden = false;
  startProcessingState(entryLoading, [
    "Reading what you told us...",
    "Turning it into resume bullets...",
    "Looking up what this role typically involves...",
  ]);

  try {
    const res = await fetch("/api/scratch-entry", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ entry_type: entryType, title, organization, dates, description }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || `Request failed (${res.status})`);
    }
    const data = await res.json();

    pendingEntry = {
      entryType,
      title,
      organization,
      location,
      dates,
      drafted_bullets: data.drafted_bullets || [],
      reflective_questions: data.reflective_questions || [],
    };

    renderEntryReview(pendingEntry);
    stopProcessingState(entryLoading);
    entryLoading.hidden = true;
    entryReview.hidden = false;
  } catch (err) {
    stopProcessingState(entryLoading);
    entryLoading.hidden = true;
    entryFormWrap.hidden = false;
    showError(entryError, err.message || "Something went wrong. Please try again.");
  }
});

function renderEntryReview(entry) {
  const bulletsEl = document.getElementById("entry-drafted-bullets");
  bulletsEl.innerHTML = "";
  entry.drafted_bullets.forEach((b) => {
    const li = document.createElement("li");
    li.textContent = b;
    bulletsEl.appendChild(li);
  });

  const questionsEl = document.getElementById("entry-questions");
  questionsEl.innerHTML = "";
  entry.reflective_questions.forEach((q) => {
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
    questionsEl.appendChild(card);
  });
}

document.getElementById("entry-confirm-btn").addEventListener("click", () => {
  if (!pendingEntry) return;

  const bullets = [...pendingEntry.drafted_bullets];
  pendingEntry.reflective_questions.forEach((q) => {
    const selected = document.querySelector(`input[name="${q.id}"]:checked`);
    if (selected && selected.value === "yes" && q.bullet_if_yes) {
      bullets.push(q.bullet_if_yes);
    }
  });

  const typeLabel = pendingEntry.entryType === "volunteer" ? " • Volunteer" : pendingEntry.entryType === "school" ? " • School Activity" : "";
  const locationPart = pendingEntry.location ? `, ${pendingEntry.location}` : "";
  const datesPart = pendingEntry.dates ? ` — ${pendingEntry.dates}` : "";
  const subtitle = `${pendingEntry.organization}${locationPart}${datesPart}${typeLabel}`;

  state.experience.push({ title: pendingEntry.title, subtitle, bullets });
  renderExperienceList();

  pendingEntry = null;
  entryReview.hidden = true;
  entryForm.reset();
  entryFormWrap.hidden = false;
});

document.getElementById("entry-discard-btn").addEventListener("click", () => {
  pendingEntry = null;
  entryReview.hidden = true;
  entryForm.reset();
  entryFormWrap.hidden = false;
});

function renderExperienceList() {
  const el = document.getElementById("experience-list");
  el.innerHTML = "";
  state.experience.forEach((entry, idx) => {
    const card = document.createElement("div");
    card.className = "entry-summary-card";
    const bulletItems = entry.bullets.map((b) => `<li>${b}</li>`).join("");
    card.innerHTML = `
      <div class="entry-summary-header">
        <strong>${entry.title}</strong>
        <button type="button" class="entry-remove-btn" data-idx="${idx}">Remove</button>
      </div>
      <span class="hint">${entry.subtitle}</span>
      <ul>${bulletItems}</ul>
    `;
    el.appendChild(card);
  });

  el.querySelectorAll(".entry-remove-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      state.experience.splice(Number(btn.dataset.idx), 1);
      renderExperienceList();
    });
  });
}

document.getElementById("experience-continue-btn").addEventListener("click", () => {
  // Fixed 2026-07-14: this used to let you navigate away while a drafted
  // entry was still sitting unconfirmed, silently losing it - the drafted
  // bullets and questions existed on screen but were never in state.experience.
  if (pendingEntry) {
    showError(
      document.getElementById("entry-error"),
      "You have an experience entry waiting for your review just above — click \"Looks good, add it\" or \"Discard this one\" first."
    );
    return;
  }
  goToStep("education");
});

// --- Step 3: Education -----------------------------------------------
document.getElementById("education-form").addEventListener("submit", (e) => {
  e.preventDefault();
  const degree = document.getElementById("edu-degree").value.trim();
  const school = document.getElementById("edu-school").value.trim();
  const location = document.getElementById("edu-location").value.trim();
  const date = document.getElementById("edu-date").value.trim();

  if (!degree || !school) return;

  const locationPart = location ? `, ${location}` : "";
  const datePart = date ? ` (${date})` : "";
  state.education.push(`${degree} – ${school}${locationPart}${datePart}`);
  renderEducationList();
  e.target.reset();
});

function renderEducationList() {
  const el = document.getElementById("education-list");
  el.innerHTML = "";
  state.education.forEach((line, idx) => {
    const div = document.createElement("div");
    div.className = "entry-summary-card";
    div.innerHTML = `
      <div class="entry-summary-header">
        <span>${line}</span>
        <button type="button" class="entry-remove-btn" data-idx="${idx}">Remove</button>
      </div>
    `;
    el.appendChild(div);
  });

  el.querySelectorAll(".entry-remove-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      state.education.splice(Number(btn.dataset.idx), 1);
      renderEducationList();
    });
  });
}

document.getElementById("education-continue-btn").addEventListener("click", () => {
  goToStep("skills");
});

// --- Step 4: Skills ----------------------------------------------------
document.getElementById("skill-form").addEventListener("submit", (e) => {
  e.preventDefault();
  const input = document.getElementById("skill-input");
  const value = input.value.trim();
  if (!value || state.skills.includes(value)) {
    input.value = "";
    return;
  }
  state.skills.push(value);
  renderSkillsList();
  input.value = "";
});

function renderSkillsList() {
  const el = document.getElementById("skills-list");
  el.innerHTML = "";
  state.skills.forEach((skill, idx) => {
    const li = document.createElement("li");
    li.className = "skill-tag";
    li.innerHTML = `${skill} <button type="button" data-idx="${idx}">&times;</button>`;
    el.appendChild(li);
  });
  el.querySelectorAll("button").forEach((btn) => {
    btn.addEventListener("click", () => {
      state.skills.splice(Number(btn.dataset.idx), 1);
      renderSkillsList();
    });
  });
}

document.getElementById("skills-continue-btn").addEventListener("click", async () => {
  goToStep("review");
  await runFinalize();
});

// --- Step 5: Review -----------------------------------------------------
let suggestedSkills = [];

async function runFinalize() {
  const reviewLoading = document.getElementById("review-loading");
  const reviewContent = document.getElementById("review-content");
  reviewLoading.hidden = false;
  reviewContent.hidden = true;
  startProcessingState(reviewLoading, [
    "Reviewing your experience...",
    "Drafting your summary...",
    "Suggesting a few more skills...",
  ]);

  try {
    const res = await fetch("/api/scratch-finalize", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        name: state.basics.name,
        experience: state.experience,
        education: state.education,
        existing_skills: state.skills,
      }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || `Request failed (${res.status})`);
    }
    const data = await res.json();

    document.getElementById("review-summary").value = data.suggested_summary || "";
    suggestedSkills = data.suggested_skills || [];
    renderSuggestedSkills();

    stopProcessingState(reviewLoading);
    reviewLoading.hidden = true;
    reviewContent.hidden = false;
  } catch (err) {
    stopProcessingState(reviewLoading);
    reviewLoading.hidden = true;
    reviewContent.hidden = false;
    document.getElementById("review-summary").value = "";
    showError(document.getElementById("generate-error"), err.message || "Couldn't put together suggestions, but you can still write your own summary below and generate your resume.");
  }
}

function renderSuggestedSkills() {
  const el = document.getElementById("suggested-skills-list");
  el.innerHTML = "";
  suggestedSkills.forEach((skill, idx) => {
    const label = document.createElement("label");
    label.className = "checkbox-field";
    label.innerHTML = `<input type="checkbox" data-skill-idx="${idx}" /><span>${skill}</span>`;
    el.appendChild(label);
  });
}

document.getElementById("generate-btn").addEventListener("click", async () => {
  const generateError = document.getElementById("generate-error");
  generateError.hidden = true;

  const contactParts = [];
  if (state.basics.city || state.basics.state) {
    contactParts.push([state.basics.city, state.basics.state].filter(Boolean).join(", "));
  }
  if (state.basics.phone) contactParts.push(state.basics.phone);
  if (state.basics.email) contactParts.push(state.basics.email);
  if (state.basics.linkedin) contactParts.push(state.basics.linkedin);

  const checkedSuggested = Array.from(document.querySelectorAll("#suggested-skills-list input:checked")).map(
    (input) => suggestedSkills[Number(input.dataset.skillIdx)]
  );

  const resumeData = {
    name: state.basics.name,
    contact: contactParts.join(" | "),
    summary: document.getElementById("review-summary").value.trim(),
    skills: [...state.skills, ...checkedSuggested],
    experience: state.experience,
    education: state.education,
  };

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
    a.download = (resumeData.name || "Resume").replace(/\s+/g, "_") + "_Resume.docx";
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
