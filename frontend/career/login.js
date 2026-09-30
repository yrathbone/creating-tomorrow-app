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

async function loadExperiences() {
  const res = await authedFetch("/api/career/experiences");
  const experiences = await res.json();

  experienceList.textContent = "";
  if (!Array.isArray(experiences) || experiences.length === 0) {
    const li = document.createElement("li");
    li.className = "hint";
    li.textContent = "No roles added yet.";
    experienceList.appendChild(li);
    return;
  }

  for (const exp of experiences) {
    const li = document.createElement("li");
    const dates = [exp.start_date, exp.end_date].filter(Boolean).join(" – ");
    li.textContent = exp.title + " — " + exp.organization + (dates ? " (" + dates + ")" : "");
    experienceList.appendChild(li);
  }
}

async function loadEducation() {
  const res = await authedFetch("/api/career/education");
  const entries = await res.json();

  educationList.textContent = "";
  if (!Array.isArray(entries) || entries.length === 0) {
    const li = document.createElement("li");
    li.className = "hint";
    li.textContent = "No education added yet.";
    educationList.appendChild(li);
    return;
  }

  for (const entry of entries) {
    const li = document.createElement("li");
    const parts = [entry.degree, entry.field_of_study].filter(Boolean).join(", ");
    li.textContent = entry.institution + (parts ? " — " + parts : "") + (entry.graduation_date ? " (" + entry.graduation_date + ")" : "");
    educationList.appendChild(li);
  }
}

async function loadCertifications() {
  const res = await authedFetch("/api/career/certifications");
  const entries = await res.json();

  certificationsList.textContent = "";
  if (!Array.isArray(entries) || entries.length === 0) {
    const li = document.createElement("li");
    li.className = "hint";
    li.textContent = "No certifications added yet.";
    certificationsList.appendChild(li);
    return;
  }

  for (const entry of entries) {
    const li = document.createElement("li");
    li.textContent = entry.name + (entry.issuer ? " — " + entry.issuer : "") + (entry.date ? " (" + entry.date + ")" : "");
    certificationsList.appendChild(li);
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
  await loadExperiences();
  await loadEducation();
  await loadCertifications();
}

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
