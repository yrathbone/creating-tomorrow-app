const loginForm = document.getElementById("login-form");
const loginError = document.getElementById("login-error");
const loginBtn = document.getElementById("login-btn");

const consentBtn = document.getElementById("consent-btn");
const consentError = document.getElementById("consent-error");

const experienceForm = document.getElementById("experience-form");
const expError = document.getElementById("exp-error");
const expSubmitBtn = document.getElementById("exp-submit-btn");
const experienceList = document.getElementById("experience-list");

const educationForm = document.getElementById("education-form");
const eduError = document.getElementById("edu-error");
const eduSubmitBtn = document.getElementById("edu-submit-btn");
const educationList = document.getElementById("education-list");

const certificationForm = document.getElementById("certification-form");
const certError = document.getElementById("cert-error");
const certSubmitBtn = document.getElementById("cert-submit-btn");
const certificationsList = document.getElementById("certifications-list");

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

function makeListRow(text, onDelete) {
  const li = document.createElement("li");
  li.className = "list-row";
  const span = document.createElement("span");
  span.className = "list-row-text";
  span.textContent = text;
  li.appendChild(span);

  const actions = document.createElement("span");
  actions.className = "list-row-actions";
  const deleteBtn = document.createElement("button");
  deleteBtn.type = "button";
  deleteBtn.className = "entry-remove-btn";
  deleteBtn.textContent = "Delete";
  deleteBtn.addEventListener("click", onDelete);
  actions.appendChild(deleteBtn);
  li.appendChild(actions);

  return li;
}

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

async function loadExperiences() {
  const res = await authedFetch("/api/career/experiences");
  allExperiences = await res.json();
  if (!Array.isArray(allExperiences)) allExperiences = [];

  experienceList.textContent = "";
  if (allExperiences.length === 0) {
    const li = document.createElement("li");
    li.className = "hint";
    li.textContent = "No roles added yet.";
    experienceList.appendChild(li);
  } else {
    for (const exp of allExperiences) {
      experienceList.appendChild(makeListRow(experienceLabel(exp), async () => {
        await authedFetch("/api/career/experiences/" + exp.id, { method: "DELETE" });
        await loadExperiences();
        updateDashboardSummary();
      }));
    }
  }
  updateDashboardSummary();
}

async function loadEducation() {
  const res = await authedFetch("/api/career/education");
  allEducation = await res.json();
  if (!Array.isArray(allEducation)) allEducation = [];

  educationList.textContent = "";
  if (allEducation.length === 0) {
    const li = document.createElement("li");
    li.className = "hint";
    li.textContent = "No education added yet.";
    educationList.appendChild(li);
  } else {
    for (const entry of allEducation) {
      educationList.appendChild(makeListRow(educationLabel(entry), async () => {
        await authedFetch("/api/career/education/" + entry.id, { method: "DELETE" });
        await loadEducation();
        updateDashboardSummary();
      }));
    }
  }
  updateDashboardSummary();
}

async function loadCertifications() {
  const res = await authedFetch("/api/career/certifications");
  allCertifications = await res.json();
  if (!Array.isArray(allCertifications)) allCertifications = [];

  certificationsList.textContent = "";
  if (allCertifications.length === 0) {
    const li = document.createElement("li");
    li.className = "hint";
    li.textContent = "No certifications added yet.";
    certificationsList.appendChild(li);
  } else {
    for (const entry of allCertifications) {
      certificationsList.appendChild(makeListRow(certificationLabel(entry), async () => {
        await authedFetch("/api/career/certifications/" + entry.id, { method: "DELETE" });
        await loadCertifications();
        updateDashboardSummary();
      }));
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
      for (const exp of allExperiences.slice(0, 3)) {
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
}

function revealCareerProfileDetail() {
  const detail = document.getElementById("career-profile-detail");
  detail.hidden = false;
  detail.scrollIntoView({ behavior: "smooth", block: "start" });
}

document.getElementById("view-full-profile-btn").addEventListener("click", revealCareerProfileDetail);
document.getElementById("update-profile-btn").addEventListener("click", revealCareerProfileDetail);

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
      throw new Error(body.detail || "Couldn't save consent.");
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
      throw new Error(body.detail || "Couldn't add that role.");
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
      throw new Error(body.detail || "Couldn't add that education entry.");
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
      throw new Error(body.detail || "Couldn't add that certification.");
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
