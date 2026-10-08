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

// The access token for the current request, in memory only. The session itself
// lives in the Cognito SDK's tab-scoped sessionStorage (see js/auth.js); before
// each call we ask the SDK for the current session, which refreshes expired
// tokens for us. Phase 1B replaced "a refresh means signing in again".
let currentAccessToken = null;
let sessionEnding = false;
const AUTH_NOTICE_KEY = "ct.auth-notice";

const SESSION_ENDED_MESSAGE = "Your session has ended. Please sign in again.";

// A failure that says nothing about the session itself (offline, throttled, Cognito
// hiccup): keep whatever is stored and let the person try again.
function isTransientAuthError(err) {
  const code = err && err.code;
  return code === "NetworkError" || code === "TooManyRequestsException" || code === "InternalErrorException" || code === "LimitExceededException";
}

// The session can't be restored or refreshed: drop the local session, forget the
// in-memory token, and reload so every in-memory piece of the dashboard is gone
// and the signed-out login page is shown (with a short note).
function endSessionAndShowLogin(message) {
  if (sessionEnding) return;
  sessionEnding = true;
  clearCognitoSessionKeys();
  currentAccessToken = null;
  try { window.sessionStorage.setItem(AUTH_NOTICE_KEY, message || SESSION_ENDED_MESSAGE); } catch (e) { /* no notice */ }
  window.location.reload();
}

async function authedFetch(path, options = {}) {
  const send = (token) => {
    const headers = Object.assign({}, options.headers, { Authorization: "Bearer " + token });
    return fetch(path, Object.assign({}, options, { headers }));
  };

  let token;
  try {
    token = (await getValidSession()).getAccessToken().getJwtToken();
  } catch (err) {
    if (!isTransientAuthError(err)) endSessionAndShowLogin();
    throw new Error(isTransientAuthError(err) ? "Couldn't reach the sign-in service. Please try again." : SESSION_ENDED_MESSAGE);
  }
  currentAccessToken = token;
  let res = await send(token);

  if (res.status === 401) {
    // The browser thought the token was valid but the server did not: ask the SDK for
    // one fresh token and retry once. If that fails too, the session is over.
    let retryToken = null;
    try {
      retryToken = (await forceRefreshSession()).getAccessToken().getJwtToken();
    } catch (err) {
      if (isTransientAuthError(err)) throw new Error("Couldn't reach the sign-in service. Please try again.");
    }
    if (!retryToken) {
      endSessionAndShowLogin();
      throw new Error(SESSION_ENDED_MESSAGE);
    }
    currentAccessToken = retryToken;
    res = await send(retryToken);
    if (res.status === 401) {
      endSessionAndShowLogin();
      throw new Error(SESSION_ENDED_MESSAGE);
    }
  }
  return res;
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
    if (fieldDefs.card && typeof buildVisualCard === "function") {
      // The shared dashboard card (same look as scans, resumes and applications).
      const c = fieldDefs.card;
      container.classList.add("vis-grid");
      buildVisualCard({
        kind: c.kind,
        tone: c.tone,
        typeLabel: c.typeLabel,
        badge: c.badge ? c.badge(entity) : "",
        title: c.title(entity),
        lines: c.lines ? c.lines(entity) : [],
        summary: c.summary ? c.summary(entity) : "",
        footerText: c.footer ? c.footer(entity) : "",
        actions: [
          visualButton("Edit", "btn-secondary vcard-btn", renderEdit),
          visualButton("Delete", "entry-remove-btn", () => onDelete(entity)),
        ],
      }, card);
      return;
    }
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
    if (fieldDefs.card) card.classList.add("vcard-editing");
    const draft = Object.assign({}, entity);
    for (const f of fieldDefs.fields) {
      if (f.type === "select") {
        const options = typeof f.options === "function" ? f.options() : f.options;
        const current = draft[f.key] == null ? "" : String(draft[f.key]);
        card.appendChild(makeSelectField(f.label, current, options, (v) => { draft[f.key] = v ? Number(v) : null; }));
        continue;
      }
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
  card: {
    kind: "role",
    tone: "good",
    typeLabel: "Role",
    title: (e) => e.title,
    lines: (e) => [[e.organization, e.location].filter(Boolean).join(" · ")],
    summary: (e) => e.description || "",
    badge: (e) => (/^(present|current)$/i.test((e.end_date || "").trim()) ? "Current" : ""),
    footer: (e) => [e.start_date, e.end_date].filter(Boolean).join(" – "),
  },
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
  card: {
    kind: "education",
    tone: "skill",
    typeLabel: "Education",
    title: (e) => e.institution,
    lines: (e) => [[e.degree, e.field_of_study].filter(Boolean).join(", ")],
    footer: (e) => (e.graduation_date ? "Graduated " + e.graduation_date : ""),
  },
  summary: educationLabel,
  fields: [
    { key: "institution", label: "Institution" },
    { key: "degree", label: "Degree" },
    { key: "field_of_study", label: "Field of study" },
    { key: "graduation_date", label: "Graduation date" },
  ],
};

const CERTIFICATION_FIELD_DEFS = {
  card: {
    kind: "certification",
    tone: "strong",
    typeLabel: "Certification",
    title: (e) => e.name,
    lines: (e) => [e.issuer],
    footer: (e) => e.date || "",
  },
  summary: certificationLabel,
  fields: [
    { key: "name", label: "Certification name" },
    { key: "issuer", label: "Issuer" },
    { key: "date", label: "Date" },
  ],
};

const SKILL_FIELD_DEFS = {
  card: {
    kind: "skill",
    tone: "fair",
    typeLabel: "Skill",
    title: (s) => s.name,
    lines: (s) => {
      const exp = s.experience_id ? allExperiences.find((e) => e.id === s.experience_id) : null;
      return [exp ? exp.title + " — " + exp.organization : "Not tied to one role"];
    },
    summary: (s) => s.source_text || "",
    footer: (s) => (s.created_at ? "Added " + shortDate(s.created_at) : ""),
  },
  summary: skillLabel,
  detail: (s) => s.source_text || "",
  fields: [
    { key: "name", label: "Skill (a short keyword)" },
    { key: "source_text", label: "How it was used (reference only, never printed on the resume)", multiline: true },
    {
      key: "experience_id",
      label: "Which role does this belong to?",
      type: "select",
      options: () => [
        { value: "", label: "Not tied to one specific role" },
        ...allExperiences.map((e) => ({ value: String(e.id), label: e.title + " — " + e.organization })),
      ],
    },
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
  } else if (typeof skillView !== "undefined" && skillView === "groups" && typeof renderSkillGroups === "function") {
    renderSkillGroups(container);
  } else {
    for (const entry of allSkills) {
      renderDetailCard(container, entry, SKILL_FIELD_DEFS, {
        onSave: async (entity, draft) => {
          const res = await authedFetch("/api/career/skills/" + entity.id, {
            method: "PUT",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(draft),
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
  if (typeof syncSkillViewToggle === "function") syncSkillViewToggle();
  updateDashboardSummary();
}

// Career Snapshot tiles: one panel open at a time inside the snapshot card.
let activeSnapshotPanel = null;

function openSnapshotPanel(key, toggle) {
  activeSnapshotPanel = toggle && activeSnapshotPanel === key ? null : key;
  document.querySelectorAll(".snapshot-panel").forEach((p) => { p.hidden = p.id !== "panel-" + activeSnapshotPanel; });
  document.querySelectorAll(".stat-row [data-panel]").forEach((b) => b.classList.toggle("active", b.dataset.panel === activeSnapshotPanel));
  if (activeSnapshotPanel) document.getElementById("panel-" + activeSnapshotPanel).scrollIntoView({ behavior: "smooth", block: "nearest" });
}

// Both tile rows (Your Career Profile and Your Activity) open their panels the same way.
for (const rowId of ["career-stat-row", "activity-stat-row"]) {
  document.getElementById(rowId).addEventListener("click", (e) => {
    const tile = e.target.closest("[data-panel]");
    if (tile) openSnapshotPanel(tile.dataset.panel, true);
  });
}

function updateDashboardSummary() {
  const statRow = document.getElementById("career-stat-row");
  const activityRow = document.getElementById("activity-stat-row");
  if (statRow && activityRow) {
    statRow.textContent = "";
    activityRow.textContent = "";
    const scans = typeof allScanHistory !== "undefined" ? allScanHistory.length : 0;
    const resumes = typeof allResumeVersions !== "undefined" ? allResumeVersions.length : 0;
    const applied = typeof allApplications !== "undefined" ? allApplications.length : 0;
    // Each tile opens its own list right under its row (key -> #panel-<key>).
    const profileStats = [
      { key: "roles", number: allExperiences.length, label: allExperiences.length === 1 ? "Role" : "Roles" },
      { key: "education", number: allEducation.length, label: "Education" },
      { key: "certifications", number: allCertifications.length, label: allCertifications.length === 1 ? "Certification" : "Certifications" },
      { key: "skills", number: allSkills.length, label: allSkills.length === 1 ? "Skill" : "Skills" },
      { key: "languages", number: typeof allLanguages !== "undefined" ? allLanguages.length : 0, label: typeof allLanguages !== "undefined" && allLanguages.length === 1 ? "Language" : "Languages" },
    ];
    const activityStats = [
      { key: "history", number: scans, label: scans === 1 ? "Job & Skill Scan" : "Job & Skill Scans" },
      { key: "resumes", number: resumes, label: resumes === 1 ? "Resume Built" : "Resumes Built" },
      { key: "applications", number: applied, label: applied === 1 ? "Application" : "Applications" },
    ];
    const addTiles = (row, stats) => {
      for (const s of stats) {
        const card = document.createElement("button");
        card.type = "button";
        card.className = "stat-card stat-" + s.key + (activeSnapshotPanel === s.key ? " active" : "");
        card.dataset.panel = s.key;
        const num = document.createElement("span");
        num.className = "stat-number";
        num.textContent = String(s.number);
        const lbl = document.createElement("span");
        lbl.className = "stat-label";
        lbl.textContent = s.label;
        card.appendChild(num);
        card.appendChild(lbl);
        row.appendChild(card);
      }
    };
    addTiles(statRow, profileStats);
    addTiles(activityRow, activityStats);
    const li = document.createElement("a");
    li.className = "stat-card stat-linkedin";
    li.href = "../spotlight.html";
    li.innerHTML = '<span class="stat-number">in</span><span class="stat-label">Refine My LinkedIn</span>';
    activityRow.appendChild(li);
  }

  // Recently confirmed lives in the Skills tile and lists the newest skills.
  const recentList = document.getElementById("recently-confirmed-list");
  if (recentList) {
    recentList.textContent = "";
    const newest = allSkills
      .filter((skill) => skill.created_at)
      .sort((x, y) => new Date(y.created_at) - new Date(x.created_at))
      .slice(0, 5);
    if (newest.length === 0) {
      const li = document.createElement("li");
      li.className = "hint";
      li.textContent = "No skills yet. Add one below or run a skill scan.";
      recentList.appendChild(li);
    } else {
      for (const skill of newest) {
        const li = document.createElement("li");
        li.textContent = skill.name;
        recentList.appendChild(li);
      }
    }
  }
}

document.getElementById("export-profile-btn").addEventListener("click", async () => {
  const errorEl = document.getElementById("export-profile-error");
  errorEl.hidden = true;
  try {
    const res = await authedFetch("/api/career/export");
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(formatErrorDetail(err.detail, `Request failed (${res.status})`));
    }
    const data = await res.json();
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "career_profile_backup_" + new Date().toISOString().slice(0, 10) + ".json";
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  } catch (err) {
    errorEl.textContent = err.message || "Something went wrong downloading your profile.";
    errorEl.hidden = false;
  }
});

function showConsentStep() {
  document.getElementById("step-login").hidden = true;
  document.getElementById("step-consent").hidden = false;
  document.getElementById("session-check").hidden = true;
  document.getElementById("nav-signout").hidden = false;
}

async function showProfileStep() {
  document.body.classList.add("dashboard-v4");
  document.getElementById("step-login").hidden = true;
  document.getElementById("session-check").hidden = true;
  document.getElementById("nav-signout").hidden = false;
  document.getElementById("step-consent").hidden = true;
  document.getElementById("step-profile").hidden = false;
  document.getElementById("page-header").hidden = true;
  document.getElementById("main-content").classList.add("dashboard-main");
  await loadExperiences();
  await loadEducation();
  await loadCertifications();
  await loadSkills();
  await loadScanHistory();
  await loadResumeVersions();
  if (typeof loadApplications === "function") await loadApplications();
  if (typeof restoreCurrentJobTarget === "function") restoreCurrentJobTarget();
  if (typeof loadLanguages === "function") await loadLanguages();
  if (typeof loadProfileBasics === "function") await loadProfileBasics();
}

function revealCareerProfileSections(scrollToId) {
  if (scrollToId === "career-profile-editor") {
    const editor = document.getElementById("career-profile-editor");
    editor.hidden = false;
    editor.scrollIntoView({ behavior: "smooth", block: "start" });
    return;
  }
  // Everything else lives in the Career Snapshot tiles now.
  openSnapshotPanel(scrollToId === "skill-detail-list" ? "skills" : "roles", false);
}

document.getElementById("update-profile-btn").addEventListener("click", () => {
  revealCareerProfileSections("career-profile-editor");
});
// The same import flow serves a resume and a LinkedIn export; only the wording differs.
function openImportFlow(fromLinkedIn) {
  revealCareerProfileSections("career-profile-editor");
  document.getElementById("mode-resume-btn").click();
  document.getElementById("resume-upload-heading").textContent = fromLinkedIn ? "Import from LinkedIn" : "Upload your resume";
  document.getElementById("resume-linkedin-tip").hidden = !fromLinkedIn;
}

document.getElementById("upload-resume-btn").addEventListener("click", () => openImportFlow(false));
document.getElementById("import-linkedin-btn").addEventListener("click", () => openImportFlow(true));

document.getElementById("mode-manual-btn").addEventListener("click", () => {
  document.getElementById("manual-entry-section").hidden = false;
  document.getElementById("resume-entry-section").hidden = true;
});

document.getElementById("mode-resume-btn").addEventListener("click", async () => {
  document.getElementById("manual-entry-section").hidden = true;
  document.getElementById("resume-entry-section").hidden = false;
  await checkForResumeDraft();
});

// Sign Out: the SDK's own sign-out plus removal of every SDK key in this tab, then a
// reload so the dashboard's in-memory state is gone and the login form shows.
document.getElementById("nav-signout").addEventListener("click", async (e) => {
  e.preventDefault();
  if (sessionEnding) return;
  sessionEnding = true;
  e.currentTarget.setAttribute("aria-disabled", "true");
  try {
    await signOutCurrentUser();
  } finally {
    currentAccessToken = null;
    window.location.replace("login.html");
  }
});

function showLoginForm(message) {
  document.body.classList.remove("dashboard-v4");
  document.getElementById("session-check").hidden = true;
  document.getElementById("nav-signout").hidden = true;
  document.getElementById("page-header").hidden = false;
  document.getElementById("step-login").hidden = false;
  if (message) {
    loginError.textContent = message;
    loginError.hidden = false;
  }
}

// On load: if this tab holds a saved Cognito session, restore it through the SDK and
// go straight to the dashboard; otherwise show the normal login form. The SDK and the
// backend decide whether the session is valid - the stored keys are only a hint.
async function restoreSession() {
  let notice = null;
  try {
    notice = window.sessionStorage.getItem(AUTH_NOTICE_KEY);
    window.sessionStorage.removeItem(AUTH_NOTICE_KEY);
  } catch (e) { /* no notice */ }

  if (!hasStoredSessionKeys()) {
    showLoginForm(notice);
    return;
  }
  try {
    const res = await authedFetch("/api/career/me");
    if (!res.ok) throw new Error("Couldn't load your account. Please try again.");
    const me = await res.json();
    if (me.consent_given) {
      await showProfileStep();
    } else {
      showConsentStep();
    }
  } catch (err) {
    if (sessionEnding) return; // the page is being reloaded to the signed-out state
    showLoginForm((err && err.message) || "Couldn't restore your session. Please sign in.");
  }
}

// While a saved session is being checked, keep the login form from flashing.
if (hasStoredSessionKeys()) {
  document.body.classList.add("dashboard-v4");
  document.getElementById("step-login").hidden = true;
  document.getElementById("page-header").hidden = true;
  document.getElementById("session-check").hidden = false;
}
if (document.readyState === "loading") {
  // The other dashboard scripts load after this one; wait for all of them.
  document.addEventListener("DOMContentLoaded", restoreSession);
} else {
  restoreSession();
}

// Back/forward can bring back an in-memory copy of the dashboard from before Sign Out.
window.addEventListener("pageshow", (e) => {
  if (e.persisted && !hasStoredSessionKeys()) window.location.reload();
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
