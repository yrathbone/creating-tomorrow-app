// General resume: build a polished resume straight from the whole Career
// Profile, no job posting required - the non-targeted counterpart to
// jobMatch.js's job-targeted builder. Relies on authedFetch()/
// formatErrorDetail() from login.js and startProcessingState()/
// stopProcessingState() from loading.js, both loaded before this file.

const generalResumeState = {
  resumeData: null,
};

const generalResumeEmpty = document.getElementById("general-resume-empty");
const generalResumeForm = document.getElementById("general-resume-form");
const generalResumeLoading = document.getElementById("general-resume-loading");
const generalResumeDone = document.getElementById("general-resume-done");

function hideAllGeneralResumeStates() {
  generalResumeEmpty.hidden = true;
  generalResumeForm.hidden = true;
  generalResumeLoading.hidden = true;
  generalResumeDone.hidden = true;
}

function startGeneralResumeFlow() {
  document.getElementById("general-resume-card").scrollIntoView({ behavior: "smooth", block: "start" });
  hideAllGeneralResumeStates();
  generalResumeForm.hidden = false;
  prefillResumeHeader(document.getElementById("general-resume-name"), document.getElementById("general-resume-contact"));
}

document.getElementById("general-resume-hero-btn").addEventListener("click", startGeneralResumeFlow);
document.getElementById("general-resume-hero-btn-2").addEventListener("click", startGeneralResumeFlow);
document.getElementById("general-resume-start-btn").addEventListener("click", startGeneralResumeFlow);

document.getElementById("general-resume-cancel-btn").addEventListener("click", () => {
  hideAllGeneralResumeStates();
  generalResumeEmpty.hidden = false;
});

document.getElementById("general-resume-build-btn").addEventListener("click", async () => {
  const errorEl = document.getElementById("general-resume-error");
  errorEl.hidden = true;

  const name = document.getElementById("general-resume-name").value.trim();
  const contact = document.getElementById("general-resume-contact").value.trim();
  if (!name || !contact) {
    errorEl.textContent = "Please fill in both your name and a contact line.";
    errorEl.hidden = false;
    return;
  }
  if (!confirmHeaderDetails(name, contact)) return;

  hideAllGeneralResumeStates();
  generalResumeLoading.hidden = false;
  startProcessingState(generalResumeLoading, [
    "Reviewing your Career Profile...",
    "Organizing your experience...",
    "Finalizing formatting...",
  ]);

  try {
    const res = await authedFetch("/api/career/build-general-resume", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name, contact }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(formatErrorDetail(err.detail, `Request failed (${res.status})`));
    }
    const data = await res.json();
    generalResumeState.resumeData = data.resume_data;

    stopProcessingState(generalResumeLoading);
    hideAllGeneralResumeStates();
    generalResumeDone.hidden = false;
    carryLayoutChoice("general-build-layout", "general-resume-template");
    if (typeof loadResumeVersions === "function") loadResumeVersions();
  } catch (err) {
    stopProcessingState(generalResumeLoading);
    hideAllGeneralResumeStates();
    generalResumeForm.hidden = false;
    errorEl.textContent = err.message || "Something went wrong building your resume.";
    errorEl.hidden = false;
  }
});

document.getElementById("general-resume-download-btn").addEventListener("click", async () => {
  const button = document.getElementById("general-resume-download-btn");
  const messageEl = document.getElementById("general-download-msg");
  clearResumeDownloadMessage(messageEl);
  if (!generalResumeState.resumeData) {
    showResumeDownloadMessage(messageEl, RESUME_NOT_READY_MESSAGE);
    return;
  }
  button.disabled = true;
  try {
    const res = await authedFetch("/api/generate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ resume_data: generalResumeState.resumeData, ats_mode: false, template: document.getElementById("general-resume-template").value }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(formatErrorDetail(err.detail, `Request failed (${res.status})`));
    }
    saveResumeBlob(await res.blob(), resumeFileName(generalResumeState.resumeData.name, ""));
  } catch (err) {
    showResumeDownloadMessage(messageEl, resumeDownloadErrorText(err));
  } finally {
    button.disabled = false;
  }
});

document.getElementById("general-resume-again-btn").addEventListener("click", () => {
  generalResumeState.resumeData = null;
  document.getElementById("general-resume-name").value = "";
  document.getElementById("general-resume-contact").value = "";
  hideAllGeneralResumeStates();
  generalResumeEmpty.hidden = false;
});
