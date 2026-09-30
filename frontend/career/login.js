const loginForm = document.getElementById("login-form");
const loginError = document.getElementById("login-error");
const loginBtn = document.getElementById("login-btn");

const consentBtn = document.getElementById("consent-btn");
const consentError = document.getElementById("consent-error");

const experienceForm = document.getElementById("experience-form");
const expError = document.getElementById("exp-error");
const expSubmitBtn = document.getElementById("exp-submit-btn");
const experienceList = document.getElementById("experience-list");

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

function showConsentStep() {
  document.getElementById("step-login").hidden = true;
  document.getElementById("step-consent").hidden = false;
}

async function showProfileStep() {
  document.getElementById("step-login").hidden = true;
  document.getElementById("step-consent").hidden = true;
  document.getElementById("step-profile").hidden = false;
  await loadExperiences();
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
