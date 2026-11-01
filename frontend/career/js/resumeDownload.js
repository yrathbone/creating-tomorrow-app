// Shared pieces of the "Download Resume (.docx)" buttons (general resume, tailored resume, "Download again" on a saved
// resume): the file name, saving the file, and an inline message instead of a pop-up. Loaded before generalResume.js,
// jobMatch.js and history.js.

const RESUME_NAME_PART_MAX = 40;

// One part of a file name: letters, digits and accent marks of any language, plus - . _ ; spaces become underscores.
function resumeFileNamePart(text) {
  const kept = String(text || "")
    .normalize("NFC")
    .replace(/\s+/g, "_")
    .replace(/[^\p{L}\p{N}\p{M}._-]/gu, "")
    .replace(/\.{2,}/g, ".")
    .replace(/_+/g, "_")
    .replace(/^[._-]+|[._-]+$/g, "");
  return kept.slice(0, RESUME_NAME_PART_MAX).replace(/[._-]+$/g, "");
}

// First_Last_Resume_Role.docx. The role is left out when there is none (a general resume); a missing name leaves
// "Resume.docx" or "Resume_Role.docx". No empty parts, no doubled underscores.
function resumeFileName(name, role) {
  const parts = [resumeFileNamePart(name), "Resume", resumeFileNamePart(role)].filter(Boolean);
  return parts.join("_") + ".docx";
}

function saveResumeBlob(blob, fileName) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = fileName;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

// Inline message next to the button (the element is a role="alert" paragraph, so a screen reader reads it out).
function showResumeDownloadMessage(el, text) {
  if (!el) return;
  el.textContent = text;
  el.hidden = false;
}

function clearResumeDownloadMessage(el) {
  if (!el) return;
  el.textContent = "";
  el.hidden = true;
}

const RESUME_NOT_READY_MESSAGE = "There is no resume to download yet. Build your resume first, then download it here.";
const RESUME_DOWNLOAD_FAILED_MESSAGE = "We couldn't prepare your download. Your information is still here; please try again.";

// What to tell the person when a download failed: the server's own words when it gave any, otherwise a plain sentence.
function resumeDownloadErrorText(err) {
  const text = err && err.message ? String(err.message) : "";
  return text && !/^Request failed/.test(text) ? text : RESUME_DOWNLOAD_FAILED_MESSAGE;
}
