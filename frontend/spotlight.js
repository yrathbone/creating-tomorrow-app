// All state lives in this browser tab for this session only - nothing is
// persisted server-side or in local storage (matches the rest of the site:
// "we don't store your information after your session ends"). Screenshots
// are held as File objects in memory until the person clicks "Review My
// Profile" - they're never uploaded anywhere until that one request.
const state = {
  screenshots: [], // File objects
  pdfFile: null,
};

let lastReviewData = null; // the most recent completed review, for the download button

function showError(el, message) {
  el.textContent = message;
  el.hidden = false;
}

// --- Expandable input-option panels ---------------------------------------
// Each of the 3 option buttons toggles its own panel open/closed - any
// number can be open at once, since inputs are combinable (per the approved
// plan), not an exclusive either/or choice.
document.querySelectorAll(".input-option-toggle").forEach((btn) => {
  btn.addEventListener("click", () => {
    const panel = document.getElementById(btn.dataset.target);
    const isOpen = !panel.hidden;
    panel.hidden = isOpen;
    btn.setAttribute("aria-expanded", String(!isOpen));
  });
});

// --- Screenshots -----------------------------------------------------------
const screenshotInput = document.getElementById("screenshot-input");
const screenshotThumbs = document.getElementById("screenshot-thumbs");

screenshotInput.addEventListener("change", () => {
  // Appends to the existing list rather than replacing it, so choosing
  // files twice (e.g. "add another") accumulates instead of overwriting -
  // the <input> itself is cleared after each pick so the same file could
  // even be re-added if someone wanted to.
  state.screenshots.push(...Array.from(screenshotInput.files));
  screenshotInput.value = "";
  renderScreenshotThumbs();
  updateReviewButtonState();
});

function renderScreenshotThumbs() {
  screenshotThumbs.innerHTML = "";
  state.screenshots.forEach((file, idx) => {
    const wrap = document.createElement("div");
    wrap.className = "screenshot-thumb";

    const img = document.createElement("img");
    img.src = URL.createObjectURL(file);
    img.alt = `Screenshot ${idx + 1} preview`;
    wrap.appendChild(img);

    const removeBtn = document.createElement("button");
    removeBtn.type = "button";
    removeBtn.className = "screenshot-thumb-remove";
    removeBtn.setAttribute("aria-label", `Remove screenshot ${idx + 1}`);
    removeBtn.textContent = "×";
    removeBtn.addEventListener("click", () => {
      URL.revokeObjectURL(img.src);
      state.screenshots.splice(idx, 1);
      renderScreenshotThumbs();
      updateReviewButtonState();
    });
    wrap.appendChild(removeBtn);

    screenshotThumbs.appendChild(wrap);
  });
}

// --- Paste Your Profile -----------------------------------------------------
const pasteEverythingToggle = document.getElementById("paste-everything-toggle");
const pasteStructured = document.getElementById("paste-structured");
const pasteEverythingWrap = document.getElementById("paste-everything-wrap");
let pasteEverythingMode = false;

pasteEverythingToggle.addEventListener("click", () => {
  pasteEverythingMode = !pasteEverythingMode;
  pasteStructured.hidden = pasteEverythingMode;
  pasteEverythingWrap.hidden = !pasteEverythingMode;
  pasteEverythingToggle.textContent = pasteEverythingMode
    ? "Use separate fields instead"
    : "Paste everything instead";
});

["paste-headline", "paste-about", "paste-experience", "paste-skills", "paste-additional", "paste-everything"].forEach((id) => {
  document.getElementById(id).addEventListener("input", updateReviewButtonState);
});

// --- Upload Profile PDF ------------------------------------------------------
const pdfInput = document.getElementById("pdf-input");
const pdfSelectedName = document.getElementById("pdf-selected-name");

pdfInput.addEventListener("change", () => {
  state.pdfFile = pdfInput.files[0] || null;
  if (state.pdfFile) {
    pdfSelectedName.textContent = `Selected: ${state.pdfFile.name}`;
    pdfSelectedName.hidden = false;
  } else {
    pdfSelectedName.hidden = true;
  }
  updateReviewButtonState();
});

// --- Enable/disable the primary CTA -----------------------------------------
const reviewBtn = document.getElementById("review-btn");

function hasAnyPastedText() {
  if (pasteEverythingMode) {
    return document.getElementById("paste-everything").value.trim().length > 0;
  }
  return ["paste-headline", "paste-about", "paste-experience", "paste-skills", "paste-additional"].some(
    (id) => document.getElementById(id).value.trim().length > 0
  );
}

function updateReviewButtonState() {
  const hasContent = state.screenshots.length > 0 || state.pdfFile !== null || hasAnyPastedText();
  reviewBtn.disabled = !hasContent;
}

// --- Submit ------------------------------------------------------------------
const stepInput = document.getElementById("step-input");
const stepLoading = document.getElementById("step-loading");
const stepResults = document.getElementById("step-results");
const inputError = document.getElementById("input-error");

const PROCESSING_MESSAGES = [
  "Got it. Let me look at how your profile tells your story.",
  "Reading what you've shared...",
  "Looking at how your story comes across...",
  "Identifying what's already working...",
  "Preparing your review...",
];

reviewBtn.addEventListener("click", async () => {
  inputError.hidden = true;

  const formData = new FormData();
  state.screenshots.forEach((file) => formData.append("screenshots", file));
  if (state.pdfFile) formData.append("profile_pdf", state.pdfFile);

  if (pasteEverythingMode) {
    formData.append("everything", document.getElementById("paste-everything").value.trim());
  } else {
    formData.append("headline", document.getElementById("paste-headline").value.trim());
    formData.append("about", document.getElementById("paste-about").value.trim());
    formData.append("experience", document.getElementById("paste-experience").value.trim());
    formData.append("skills", document.getElementById("paste-skills").value.trim());
    formData.append("additional", document.getElementById("paste-additional").value.trim());
  }

  reviewBtn.disabled = true;
  stepInput.hidden = true;
  stepLoading.hidden = false;
  startProcessingState(stepLoading, PROCESSING_MESSAGES);

  try {
    const res = await fetch("/api/profile-review", { method: "POST", body: formData });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || `Request failed (${res.status})`);
    }
    const data = await res.json();

    stopProcessingState(stepLoading);
    stepLoading.hidden = true;
    renderResults(data);
    stepResults.hidden = false;
  } catch (err) {
    stopProcessingState(stepLoading);
    stepLoading.hidden = true;
    stepInput.hidden = false;
    showError(inputError, err.message || "Something went wrong. Please try again.");
  } finally {
    reviewBtn.disabled = false;
  }
});

// --- Rendering results ---------------------------------------------------
function fillList(elementId, items) {
  const el = document.getElementById(elementId);
  el.innerHTML = "";
  (items || []).forEach((item) => {
    const li = document.createElement("li");
    li.textContent = item;
    el.appendChild(li);
  });
}

function renderResults(data) {
  lastReviewData = data;
  const insufficientBlock = document.getElementById("insufficient-info-block");
  const resultsSections = document.getElementById("results-sections");

  if (data.insufficient_information) {
    insufficientBlock.textContent =
      data.insufficient_information_message ||
      "I need a little more profile information before I can give you a useful review.";
    insufficientBlock.hidden = false;
    resultsSections.hidden = true;
    return;
  }
  insufficientBlock.hidden = true;
  resultsSections.hidden = false;

  // 1. First impression
  const fi = data.first_impression || {};
  fillList("fi-working", fi.whats_working);
  fillList("fi-clearer", fi.could_be_clearer);
  document.getElementById("fi-why").textContent = fi.why_it_matters || "";

  // 2. Headline
  renderSection(data.headline, "headline", {
    working: "headline-working",
    clearer: "headline-clearer",
    why: "headline-why",
    note: "headline-note",
    detail: "headline-detail",
  });
  if (data.headline && data.headline.supplied) {
    document.getElementById("headline-current").textContent = data.headline.current || "";
    document.getElementById("headline-suggested").textContent = data.headline.suggested || "";
  }

  // 3. About
  renderSection(data.about, "about", {
    working: "about-working",
    clearer: "about-clearer",
    why: "about-why",
    note: "about-note",
    detail: "about-detail",
  });
  if (data.about && data.about.supplied) {
    document.getElementById("about-suggested").textContent = data.about.suggested_revision || "";
  }

  // 4. Experience
  const exp = data.experience || {};
  const expNote = document.getElementById("experience-note");
  const expDetail = document.getElementById("experience-detail");
  if (!exp.supplied) {
    expNote.textContent = exp.note || "I don't have your experience yet - paste it or include a screenshot, and I'll take a look.";
    expNote.hidden = false;
    expDetail.hidden = true;
  } else {
    expNote.hidden = true;
    expDetail.hidden = false;
    fillList("exp-working", exp.whats_working);
    fillList("exp-lost", exp.may_be_getting_lost);
    fillList("exp-suggestions", exp.suggested_improvements);
    document.getElementById("exp-why").textContent = exp.why || "";
  }

  // 5. Skills
  const skills = data.skills || {};
  fillList("skills-clear", skills.clearly_demonstrated);
  fillList("skills-possible", skills.possible_to_consider);
  fillList("skills-needs-more", skills.needs_more_information);

  // Signature strengths
  const strengthsList = document.getElementById("strengths-list");
  strengthsList.innerHTML = "";
  (data.strengths || []).forEach((strength) => {
    const card = document.createElement("div");
    card.className = "strength-card";
    const h4 = document.createElement("h4");
    h4.textContent = strength.title;
    const p = document.createElement("p");
    p.textContent = strength.evidence;
    card.appendChild(h4);
    card.appendChild(p);
    strengthsList.appendChild(card);
  });
}

function renderSection(sectionData, prefix, ids) {
  const note = document.getElementById(ids.note);
  const detail = document.getElementById(ids.detail);
  const section = sectionData || {};

  if (!section.supplied) {
    note.textContent = section.note || `I don't have your ${prefix} yet - paste it or include a screenshot, and I'll take a look.`;
    note.hidden = false;
    detail.hidden = true;
    return;
  }

  note.hidden = true;
  detail.hidden = false;
  fillList(ids.working, section.whats_working);
  fillList(ids.clearer, section.could_be_clearer);
  document.getElementById(ids.why).textContent = section.why || "";
}

// --- Copy buttons (delegated - results are rendered dynamically) -----------
// navigator.clipboard.writeText() can reject for reasons outside our control
// (no permission, an older browser, a background/unfocused tab) - without a
// .catch() the button would just silently do nothing, leaving the person
// unsure whether it worked. The fallback selects the text so they can still
// copy it manually with their own keyboard shortcut.
document.getElementById("step-results").addEventListener("click", (e) => {
  const btn = e.target.closest(".copy-btn");
  if (!btn) return;
  const target = document.getElementById(btn.dataset.copyTarget);
  if (!target) return;

  const original = btn.textContent;
  navigator.clipboard
    .writeText(target.textContent)
    .then(() => {
      btn.textContent = "Copied!";
      setTimeout(() => (btn.textContent = original), 1500);
    })
    .catch(() => {
      const range = document.createRange();
      range.selectNodeContents(target);
      const selection = window.getSelection();
      selection.removeAllRanges();
      selection.addRange(range);
      btn.textContent = "Selected — press Ctrl+C";
      setTimeout(() => (btn.textContent = original), 2500);
    });
});

// --- Download report ---------------------------------------------------------
const downloadReportBtn = document.getElementById("download-report-btn");
const downloadReportError = document.getElementById("download-report-error");

downloadReportBtn.addEventListener("click", async () => {
  downloadReportError.hidden = true;
  if (!lastReviewData) return;

  downloadReportBtn.disabled = true;
  try {
    const res = await fetch("/api/spotlight-recap", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ review: lastReviewData }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || `Request failed (${res.status})`);
    }
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "Spotlight_Report.docx";
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  } catch (err) {
    showError(downloadReportError, err.message || "Something went wrong generating your report.");
  } finally {
    downloadReportBtn.disabled = false;
  }
});

// --- Start over --------------------------------------------------------------
document.getElementById("start-over-btn").addEventListener("click", () => {
  stepResults.hidden = true;
  stepInput.hidden = false;
});
