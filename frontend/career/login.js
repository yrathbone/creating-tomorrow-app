// FastAPI's own validation errors (422s) put an ARRAY of {loc, msg, type}
// objects in `detail`, not a string - passing that straight into
// `new Error(...)` stringified it as "[object Object]" everywhere in this
// feature. This normalizes any shape (string, validation-error array,
// single object, or nothing) into an actual readable message.
function formatErrorDetail(detail, fallback) {
  if (!detail) return fallback;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail.map((d) => (d && d.msg) ? `${(d.loc || []).join(".")}: ${d.msg}` : JSON.stringify(d)).join("; ");
  }
  if (typeof detail === "object") return detail.msg || JSON.stringify(detail);
  return String(detail);
}

const loginForm = document.getElementById("login-form");
const loginError = document.getElementById("login-error");
const loginBtn = document.getElementById("login-btn");

const consentBtn = document.getElementById("consent-btn");
const consentError = document.getElementById("consent-error");

const experienceForm = document.getElementById("experience-form");
const expError = document.getElementById("exp-error");
const expSubmitBtn = document.getElementById("exp-submit-btn");

const educationForm = document.getElementById("education-form");
const eduError = document.getElementById("edu-error");
const eduSubmitBtn = document.getElementById("edu-submit-btn");

const certificationForm = document.getElementById("certification-form");
const certError = document.getElementById("cert-error");
const certSubmitBtn = document.getElementById("cert-submit-btn");

const skillForm = document.getElementById("skill-form");
const skillError = document.getElementById("skill-error");
const skillSubmitBtn = document.getElementById("skill-submit-btn");

// Kept in memory only, never persisted - a hard refresh means signing in
// again (Deliverable C's deliberate MVP tradeoff).
let currentAccessToken = null;

function authedFetch(path, options = {}) {
  const headers = Object.assign({}, options.headers, {
    Authorization: "Bearer " + currentAccessToken,
  });
  return fetch(path, Object.assign({}, options, { headers }));
}

// Populated by loadExperiences/loadEducation/loadCertifications - the one
// source of truth both the full detail lists and the dashboard summary
// widgets (stat counts, recently confirmed, role preview) render from, so
// there's exactly one fetch per entity type, not one per view.
let allExperiences = [];
let allEducation = [];
let allCertifications = [];
let allSkills = [];

// Generic editable/deletable detail card - view mode shows a summary line
// plus Edit/Delete; Edit swaps in text fields with Save/Cancel. Used for
// Experience, Education, and Certification detail lists so there's one
// implementation of "edit in place, save via PUT" rather than three.
function renderDetailCard(container, entity, fieldDefs, { onSave, onDelete }) {
  const card = document.createElement("div");
  card.className = "entry-summary-card";

  function renderView() {
    card.innerHTML = "";
    const header = document.createElement("div");
    header.className = "entry-summary-header";
    const summary = document.createElement("strong");
    summary.textContent = fieldDefs.summary(entity);
    const actions = document.createElement("span");
    actions.className = "list-row-actions";
    const editBtn = document.createElement("button");
    editBtn.type = "button";
    editBtn.className = "entry-remove-btn";
    editBtn.textContent = "Edit";
    editBtn.addEventListener("click", renderEdit);
    const deleteBtn = document.createElement("button");
    deleteBtn.type = "button";
    deleteBtn.className = "entry-remove-btn";
    deleteBtn.textContent = "Delete";
    deleteBtn.addEventListener("click", () => onDelete(entity));
    actions.appendChild(editBtn);
    actions.appendChild(deleteBtn);
    header.appendChild(summary);
    header.appendChild(actions);
    card.appendChild(header);

    const detailText = fieldDefs.detail ? fieldDefs.detail(entity) : "";
    if (detailText) {
      const p = document.createElement("p");
      p.className = "hint";
      p.style.whiteSpace = "pre-line";
      p.textContent = detailText;
      card.appendChild(p);
    }
  }

  function renderEdit() {
    card.innerHTML = "";
    const draft = Object.assign({}, entity);
    for (const f of fieldDefs.fields) {
      const makeField = f.multiline ? makeTextareaField : makeTextField;
      card.appendChild(makeField(f.label, draft[f.key], (v) => { draft[f.key] = v; }));
    }

    const saveBtn = document.createElement("button");
    saveBtn.type = "button";
    saveBtn.textContent = "Save";
    const cancelBtn = document.createElement("button");
    cancelBtn.type = "button";
    cancelBtn.className = "btn-secondary";
    cancelBtn.textContent = "Cancel";
    cancelBtn.addEventListener("click", renderView);

    const saveError = document.createElement("div");
    saveError.className = "error";
    saveError.hidden = true;

    saveBtn.addEventListener("click", async () => {
      saveError.hidden = true;
      saveBtn.disabled = true;
      try {
        await onSave(entity, draft);
      } catch (err) {
        saveError.textContent = (err && err.message) || "Couldn't save that change.";
        saveError.hidden = false;
        saveBtn.disabled = false;
        return;
      }
      saveBtn.disabled = false;
    });

    card.appendChild(saveBtn);
    card.appendChild(cancelBtn);
    card.appendChild(saveError);
  }

  renderView();
  container.appendChild(card);
}

// makeTextField is defined in resumeReview.js (loaded before this file) and
// reused here for the same "label + input, onInput updates a draft object"
// pattern used by the resume-review edit cards.

function experienceLabel(exp) {
  const dates = [exp.start_date, exp.end_date].filter(Boolean).join(" – ");
  return exp.title + " — " + exp.organization + (dates ? " (" + dates + ")" : "");
}

function educationLabel(entry) {
  const parts = [entry.degree, entry.field_of_study].filter(Boolean).join(", ");
  return entry.institution + (parts ? " — " + parts : "") + (entry.graduation_date ? " (" + entry.graduation_date + ")" : "");
}

function certificationLabel(entry) {
  return entry.name + (entry.issuer ? " — " + entry.issuer : "") + (entry.date ? " (" + entry.date + ")" : "");
}

function skillLabel(entry) {
  if (entry.experience_id) {
    const exp = allExperiences.find((e) => e.id === entry.experience_id);
    if (exp) return entry.name + " (" + exp.title + " — " + exp.organization + ")";
  }
  return entry.name;
}

const EXPERIENCE_FIELD_DEFS = {
  summary: experienceLabel,
  detail: (exp) => exp.description || "",
  fields: [
    { key: "title", label: "Title" },
    { key: "organization", label: "Organization" },
    { key: "location", label: "Location" },
    { key: "start_date", label: "Start date" },
    { key: "end_date", label: "End date" },
    { key: "description", label: "Description", multiline: true },
  ],
};

const EDUCATION_FIELD_DEFS = {
  summary: educationLabel,
  fields: [
    { key: "institution", label: "Institution" },
    { key: "degree", label: "Degree" },
    { key: "field_of_study", label: "Field of study" },
    { key: "graduation_date", label: "Graduation date" },
  ],
};

const CERTIFICATION_FIELD_DEFS = {
  summary: certificationLabel,
  fields: [
    { key: "name", label: "Certification name" },
    { key: "issuer", label: "Issuer" },
    { key: "date", label: "Date" },
  ],
};

const SKILL_FIELD_DEFS = {
  summary: skillLabel,
  detail: (s) => s.source_text || "",
  fields: [
    { key: "name", label: "Skill" },
    { key: "source_text", label: "How it was used", multiline: true },
  ],
};

// Sorts by actual role date (start_date), not by when the row was added
// to the profile - "created_at order" and "career chronology" are
// different things, and the detail view should reflect the latter.
let experienceSortDirection = "newest";

function parseDateForSort(s) {
  if (!s) return 0;
  const str = s.trim().toLowerCase();
  if (str === "present" || str === "current") return 999912;
  const match = str.match(/(\d{1,2})\D+(\d{2,4})/);
  if (match) {
    let month = parseInt(match[1], 10);
    let year = parseInt(match[2], 10);
    if (year < 100) year += year < 50 ? 2000 : 1900;
    return year * 100 + month;
  }
  const yearOnly = str.match(/(\d{4})/);
  if (yearOnly) return parseInt(yearOnly[1], 10) * 100;
  return 0;
}

function sortedExperiences() {
  const sorted = allExperiences.slice().sort((a, b) => parseDateForSort(a.start_date) - parseDateForSort(b.start_date));
  if (experienceSortDirection === "newest") sorted.reverse();
  return sorted;
}

function renderExperienceDetailList() {
  const container = document.getElementById("experience-detail-list");
  container.textContent = "";
  if (allExperiences.length === 0) {
    const p = document.createElement("p");
    p.className = "hint";
    p.textContent = "No roles added yet.";
    container.appendChild(p);
    return;
  }
  for (const exp of sortedExperiences()) {
    renderDetailCard(container, exp, EXPERIENCE_FIELD_DEFS, {
      onSave: async (entity, draft) => {
        const res = await authedFetch("/api/career/experiences/" + entity.id, {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(draft),
        });
        if (!res.ok) {
          const body = await res.json().catch(() => ({}));
          throw new Error(formatErrorDetail(body.detail, "Couldn't save that change."));
        }
        await loadExperiences();
      },
      onDelete: async (entity) => {
        await authedFetch("/api/career/experiences/" + entity.id, { method: "DELETE" });
        await loadExperiences();
      },
    });
  }
}

document.getElementById("sort-newest-btn").addEventListener("click", () => {
  experienceSortDirection = "newest";
  renderExperienceDetailList();
});
document.getElementById("sort-oldest-btn").addEventListener("click", () => {
  experienceSortDirection = "oldest";
  renderExperienceDetailList();
});

function populateSkillExperienceSelect() {
  const select = document.getElementById("skill-experience-id");
  if (!select) return;
  const previousValue = select.value;
  select.textContent = "";
  const noneOption = document.createElement("option");
  noneOption.value = "";
  noneOption.textContent = "Not tied to one specific role";
  select.appendChild(noneOption);
  for (const exp of allExperiences) {
    const option = document.createElement("option");
    option.value = String(exp.id);
    option.textContent = exp.title + " — " + exp.organization;
    select.appendChild(option);
  }
  select.value = previousValue;
}

async function loadExperiences() {
  const res = await authedFetch("/api/career/experiences");
  allExperiences = await res.json();
  if (!Array.isArray(allExperiences)) allExperiences = [];

  renderExperienceDetailList();
  populateSkillExperienceSelect();
  updateDashboardSummary();
}

async function loadEducation() {
  const res = await authedFetch("/api/career/education");
  allEducation = await res.json();
  if (!Array.isArray(allEducation)) allEducation = [];

  const container = document.getElementById("education-detail-list");
  container.textContent = "";
  if (allEducation.length === 0) {
    const p = document.createElement("p");
    p.className = "hint";
    p.textContent = "No education added yet.";
    container.appendChild(p);
  } else {
    for (const entry of allEducation) {
      renderDetailCard(container, entry, EDUCATION_FIELD_DEFS, {
        onSave: async (entity, draft) => {
          const res = await authedFetch("/api/career/education/" + entity.id, {
            method: "PUT",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(draft),
          });
          if (!res.ok) {
            const body = await res.json().catch(() => ({}));
            throw new Error(formatErrorDetail(body.detail, "Couldn't save that change."));
          }
          await loadEducation();
        },
        onDelete: async (entity) => {
          await authedFetch("/api/career/education/" + entity.id, { method: "DELETE" });
          await loadEducation();
        },
      });
    }
  }
  updateDashboardSummary();
}

async function loadCertifications() {
  const res = await authedFetch("/api/career/certifications");
  allCertifications = await res.json();
  if (!Array.isArray(allCertifications)) allCertifications = [];

  const container = document.getElementById("certification-detail-list");
  container.textContent = "";
  if (allCertifications.length === 0) {
    const p = document.createElement("p");
    p.className = "hint";
    p.textContent = "No certifications added yet.";
    container.appendChild(p);
  } else {
    for (const entry of allCertifications) {
      renderDetailCard(container, entry, CERTIFICATION_FIELD_DEFS, {
        onSave: async (entity, draft) => {
          const res = await authedFetch("/api/career/certifications/" + entity.id, {
            method: "PUT",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(draft),
          });
          if (!res.ok) {
            const body = await res.json().catch(() => ({}));
            throw new Error(formatErrorDetail(body.detail, "Couldn't save that change."));
          }
          await loadCertifications();
        },
        onDelete: async (entity) => {
          await authedFetch("/api/career/certifications/" + entity.id, { method: "DELETE" });
          await loadCertifications();
        },
      });
    }
  }
  updateDashboardSummary();
}

async function loadSkills() {
  const res = await authedFetch("/api/career/skills");
  allSkills = await res.json();
  if (!Array.isArray(allSkills)) allSkills = [];

  const container = document.getElementById("skill-detail-list");
  container.textContent = "";
  if (allSkills.length === 0) {
    const p = document.createElement("p");
    p.className = "hint";
    p.textContent = "No skills added yet.";
    container.appendChild(p);
  } else {
    for (const entry of allSkills) {
      renderDetailCard(container, entry, SKILL_FIELD_DEFS, {
        onSave: async (entity, draft) => {
          // The generic edit form doesn't expose "which role" - preserve
          // whatever was already set rather than letting Pydantic's
          // default silently clear it on every edit.
          const res = await authedFetch("/api/career/skills/" + entity.id, {
            method: "PUT",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(Object.assign({}, draft, { experience_id: entity.experience_id })),
          });
          if (!res.ok) {
            const body = await res.json().catch(() => ({}));
            throw new Error(formatErrorDetail(body.detail, "Couldn't save that change."));
          }
          await loadSkills();
        },
        onDelete: async (entity) => {
          await authedFetch("/api/career/skills/" + entity.id, { method: "DELETE" });
          await loadSkills();
        },
      });
    }
  }
  updateDashboardSummary();
}

function updateDashboardSummary() {
  const statRow = document.getElementById("career-stat-row");
  if (statRow) {
    statRow.textContent = "";
    const stats = [
      [allExperiences.length, allExperiences.length === 1 ? "Role" : "Roles"],
      [allEducation.length, "Education"],
      [allCertifications.length, allCertifications.length === 1 ? "Certification" : "Certifications"],
      [allSkills.length, allSkills.length === 1 ? "Skill" : "Skills"],
    ];
    for (const [number, label] of stats) {
      const card = document.createElement("div");
      card.className = "stat-card";
      const num = document.createElement("span");
      num.className = "stat-number";
      num.textContent = String(number);
      const lbl = document.createElement("span");
      lbl.className = "stat-label";
      lbl.textContent = label;
      card.appendChild(num);
      card.appendChild(lbl);
      statRow.appendChild(card);
    }
  }

  const recentList = document.getElementById("recently-confirmed-list");
  if (recentList) {
    recentList.textContent = "";
    const combined = [
      ...allExperiences.map((e) => ({ text: e.title + " — " + e.organization, created_at: e.created_at })),
      ...allEducation.map((e) => ({ text: e.institution, created_at: e.created_at })),
      ...allCertifications.map((e) => ({ text: e.name, created_at: e.created_at })),
      ...allSkills.map((e) => ({ text: e.name, created_at: e.created_at })),
    ]
      .filter((item) => item.created_at)
      .sort((a, b) => new Date(b.created_at) - new Date(a.created_at))
      .slice(0, 5);

    if (combined.length === 0) {
      const li = document.createElement("li");
      li.className = "hint";
      li.textContent = "We don't have enough information yet — add a role, resume, or credential to get started.";
      recentList.appendChild(li);
    } else {
      for (const item of combined) {
        const li = document.createElement("li");
        li.textContent = item.text;
        recentList.appendChild(li);
      }
    }
  }

  const rolePreview = document.getElementById("role-preview-list");
  if (rolePreview) {
    rolePreview.textContent = "";
    if (allExperiences.length === 0) {
      const p = document.createElement("p");
      p.className = "hint";
      p.textContent = "No roles yet — add one or upload a resume to get started.";
      rolePreview.appendChild(p);
    } else {
      const newestFirst = allExperiences.slice().sort((a, b) => parseDateForSort(b.start_date) - parseDateForSort(a.start_date));
      for (const exp of newestFirst.slice(0, 3)) {
        const item = document.createElement("div");
        item.className = "role-preview-item";
        const title = document.createElement("div");
        title.className = "role-title";
        title.textContent = exp.title;
        const org = document.createElement("div");
        org.className = "role-org";
        org.textContent = exp.organization;
        item.appendChild(title);
        item.appendChild(org);
        const dates = [exp.start_date, exp.end_date].filter(Boolean).join(" – ");
        if (dates) {
          const datesEl = document.createElement("div");
          datesEl.className = "role-dates";
          datesEl.textContent = dates;
          item.appendChild(datesEl);
        }
        rolePreview.appendChild(item);
      }
    }
  }

  const dashEdu = document.getElementById("dashboard-education-list");
  const dashCert = document.getElementById("dashboard-certifications-list");
  if (dashEdu) {
    dashEdu.textContent = "";
    if (allEducation.length === 0) {
      const p = document.createElement("p");
      p.className = "hint";
      p.textContent = "No education added yet.";
      dashEdu.appendChild(p);
    } else {
      for (const entry of allEducation) {
        const p = document.createElement("p");
        p.textContent = educationLabel(entry);
        dashEdu.appendChild(p);
      }
    }
  }
  if (dashCert) {
    dashCert.textContent = "";
    if (allCertifications.length === 0) {
      const p = document.createElement("p");
      p.className = "hint";
      p.textContent = "No certifications added yet.";
      dashCert.appendChild(p);
    } else {
      for (const entry of allCertifications) {
        const p = document.createElement("p");
        p.textContent = certificationLabel(entry);
        dashCert.appendChild(p);
      }
    }
  }
}

function showConsentStep() {
  document.getElementById("step-login").hidden = true;
  document.getElementById("step-consent").hidden = false;
}

async function showProfileStep() {
  document.getElementById("step-login").hidden = true;
  document.getElementById("step-consent").hidden = true;
  document.getElementById("step-profile").hidden = false;
  document.getElementById("page-header").hidden = true;
  document.getElementById("main-content").classList.add("dashboard-main");
  await loadExperiences();
  await loadEducation();
  await loadCertifications();
  await loadSkills();
}

function revealCareerProfileSections(scrollToId) {
  document.getElementById("career-profile-detail").hidden = false;
  document.getElementById("career-profile-editor").hidden = false;
  document.getElementById(scrollToId).scrollIntoView({ behavior: "smooth", block: "start" });
}

document.getElementById("view-full-profile-btn").addEventListener("click", () => {
  revealCareerProfileSections("career-profile-detail");
});
document.getElementById("update-profile-btn").addEventListener("click", () => {
  revealCareerProfileSections("career-profile-editor");
});
document.getElementById("nav-career-profile-btn").addEventListener("click", () => {
  revealCareerProfileSections("career-profile-detail");
});

document.getElementById("mode-manual-btn").addEventListener("click", () => {
  document.getElementById("manual-entry-section").hidden = false;
  document.getElementById("resume-entry-section").hidden = true;
});

document.getElementById("mode-resume-btn").addEventListener("click", async () => {
  document.getElementById("manual-entry-section").hidden = true;
  document.getElementById("resume-entry-section").hidden = false;
  await checkForResumeDraft();
});

loginForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  loginError.hidden = true;
  const email = document.getElementById("login-email").value.trim();
  const password = document.getElementById("login-password").value;

  loginBtn.disabled = true;
  try {
    const { accessToken } = await signIn(email, password);
    currentAccessToken = accessToken;

    const res = await authedFetch("/api/career/me");
    const me = await res.json();

    if (me.consent_given) {
      await showProfileStep();
    } else {
      showConsentStep();
    }
  } catch (err) {
    loginError.textContent = (err && err.message) || "Login failed.";
    loginError.hidden = false;
  } finally {
    loginBtn.disabled = false;
  }
});

consentBtn.addEventListener("click", async () => {
  consentError.hidden = true;
  consentBtn.disabled = true;
  try {
    const res = await authedFetch("/api/career/consent", { method: "POST" });
    if (!res.ok) {
      const body = await res.json();
      throw new Error(formatErrorDetail(body.detail, "Couldn't save consent."));
    }
    await showProfileStep();
  } catch (err) {
    consentError.textContent = (err && err.message) || "Couldn't save consent.";
    consentError.hidden = false;
  } finally {
    consentBtn.disabled = false;
  }
});

experienceForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  expError.hidden = true;
  expSubmitBtn.disabled = true;

  const payload = {
    title: document.getElementById("exp-title").value.trim(),
    organization: document.getElementById("exp-organization").value.trim(),
    location: document.getElementById("exp-location").value.trim(),
    start_date: document.getElementById("exp-start").value.trim(),
    end_date: document.getElementById("exp-end").value.trim(),
    description: document.getElementById("exp-description").value.trim(),
  };

  try {
    const res = await authedFetch("/api/career/experiences", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!res.ok) {
      const body = await res.json();
      throw new Error(formatErrorDetail(body.detail, "Couldn't add that role."));
    }
    experienceForm.reset();
    await loadExperiences();
  } catch (err) {
    expError.textContent = (err && err.message) || "Couldn't add that role.";
    expError.hidden = false;
  } finally {
    expSubmitBtn.disabled = false;
  }
});

educationForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  eduError.hidden = true;
  eduSubmitBtn.disabled = true;

  const payload = {
    institution: document.getElementById("edu-institution").value.trim(),
    degree: document.getElementById("edu-degree").value.trim(),
    field_of_study: document.getElementById("edu-field").value.trim(),
    graduation_date: document.getElementById("edu-graduation").value.trim(),
  };

  try {
    const res = await authedFetch("/api/career/education", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!res.ok) {
      const body = await res.json();
      throw new Error(formatErrorDetail(body.detail, "Couldn't add that education entry."));
    }
    educationForm.reset();
    await loadEducation();
  } catch (err) {
    eduError.textContent = (err && err.message) || "Couldn't add that education entry.";
    eduError.hidden = false;
  } finally {
    eduSubmitBtn.disabled = false;
  }
});

certificationForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  certError.hidden = true;
  certSubmitBtn.disabled = true;

  const payload = {
    name: document.getElementById("cert-name").value.trim(),
    issuer: document.getElementById("cert-issuer").value.trim(),
    date: document.getElementById("cert-date").value.trim(),
  };

  try {
    const res = await authedFetch("/api/career/certifications", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!res.ok) {
      const body = await res.json();
      throw new Error(formatErrorDetail(body.detail, "Couldn't add that certification."));
    }
    certificationForm.reset();
    await loadCertifications();
  } catch (err) {
    certError.textContent = (err && err.message) || "Couldn't add that certification.";
    certError.hidden = false;
  } finally {
    certSubmitBtn.disabled = false;
  }
});

skillForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  skillError.hidden = true;
  skillSubmitBtn.disabled = true;

  const experienceIdRaw = document.getElementById("skill-experience-id").value;
  const payload = {
    name: document.getElementById("skill-name").value.trim(),
    source_text: document.getElementById("skill-source-text").value.trim() || null,
    experience_id: experienceIdRaw ? Number(experienceIdRaw) : null,
  };

  try {
    const res = await authedFetch("/api/career/skills", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!res.ok) {
      const body = await res.json();
      throw new Error(formatErrorDetail(body.detail, "Couldn't add that skill."));
    }
    skillForm.reset();
    await loadSkills();
  } catch (err) {
    skillError.textContent = (err && err.message) || "Couldn't add that skill.";
    skillError.hidden = false;
  } finally {
    skillSubmitBtn.disabled = false;
  }
});
