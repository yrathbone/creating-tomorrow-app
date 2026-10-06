// All state lives in this browser tab for this session only - nothing is
// persisted server-side or in local storage (matches the rest of the site:
// "we don't store your information after your session ends"). Screenshots
// are held as File objects in memory until the person clicks "Review My
// Profile" - they're never uploaded anywhere until that one request.
const state = {
  screenshots: [], // File objects
  pdfFile: null,
  resumeFile: null, // optional - additional context only, not itself reviewed
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

// --- Add Your Resume (optional, additional context only - not itself
// reviewed, so it never counts toward enabling the button below) -----------
const resumeInput = document.getElementById("resume-input");
const resumeSelectedName = document.getElementById("resume-selected-name");

resumeInput.addEventListener("change", () => {
  state.resumeFile = resumeInput.files[0] || null;
  if (state.resumeFile) {
    resumeSelectedName.textContent = `Selected: ${state.resumeFile.name}`;
    resumeSelectedName.hidden = false;
  } else {
    resumeSelectedName.hidden = true;
  }
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
  if (state.resumeFile) formData.append("resume_file", state.resumeFile);

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
  resetCompare();
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
    const sampleAbout = data.suggested_full_profile && data.suggested_full_profile.about;
    const aboutText = data.about.suggested_revision || sampleAbout || "";
    document.getElementById("about-suggested").textContent = aboutText;
    // No text at all: hide the empty box and its Copy button instead of showing a blank.
    document.getElementById("about-suggested").closest(".suggested-text-block").hidden = !aboutText;
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

  // Sample updated profile (only present when there was enough material)
  const sampleBlock = document.getElementById("sample-profile-block");
  const sample = data.suggested_full_profile;
  if (!sample) {
    sampleBlock.hidden = true;
  } else {
    sampleBlock.hidden = false;

    const headlineBlock = document.getElementById("sample-profile-headline-block");
    if (sample.headline) {
      document.getElementById("sample-profile-headline").textContent = sample.headline;
      headlineBlock.hidden = false;
    } else {
      headlineBlock.hidden = true;
    }

    const aboutBlock = document.getElementById("sample-profile-about-block");
    if (sample.about) {
      document.getElementById("sample-profile-about").textContent = sample.about;
      aboutBlock.hidden = false;
    } else {
      aboutBlock.hidden = true;
    }

    const expContainer = document.getElementById("sample-profile-experience");
    expContainer.innerHTML = "";
    (sample.experience || []).forEach((role) => {
      const card = document.createElement("div");
      card.className = "prepare-question-card"; // reuses existing card styling, not a new visual pattern
      const h4 = document.createElement("h4");
      h4.textContent = role.organization ? `${role.title} — ${role.organization}` : role.title;
      card.appendChild(h4);
      const ul = document.createElement("ul");
      (role.bullets || []).forEach((b) => {
        const li = document.createElement("li");
        li.textContent = b;
        // A [bracketed note] is a reminder to finish the sentence on LinkedIn, not text to paste.
        if (isSampleNote(b)) {
          li.className = "sample-todo";
          li.textContent = "To finish on LinkedIn: " + b.replace(/^\s*\[|\]\s*$/g, "");
        }
        ul.appendChild(li);
      });
      card.appendChild(ul);
      const copyBtn = document.createElement("button");
      copyBtn.type = "button";
      copyBtn.className = "btn-secondary copy-btn";
      copyBtn.textContent = "Copy this role";
      copyBtn.dataset.copyText = roleCopyText(role);
      card.appendChild(copyBtn);
      expContainer.appendChild(card);
    });
  }
}

// --- Sample profile copy helpers -------------------------------------------
function isSampleNote(text) {
  return /^\s*\[.*\]\s*$/.test(text || "");
}

function roleCopyText(role) {
  const bullets = (role.bullets || []).filter((b) => !isSampleNote(b)).map((b) => "\u2022 " + b);
  const heading = role.organization ? `${role.title} \u2014 ${role.organization}` : role.title;
  return [heading, ...bullets].join("\n");
}

function wholeProfileCopyText(sample) {
  const parts = [];
  if (sample.headline) parts.push("HEADLINE\n" + sample.headline);
  if (sample.about) parts.push("ABOUT\n" + sample.about);
  const roles = (sample.experience || []).map(roleCopyText);
  if (roles.length) parts.push("EXPERIENCE\n\n" + roles.join("\n\n"));
  return parts.join("\n\n");
}

document.getElementById("sample-copy-all-btn").addEventListener("click", (e) => {
  if (!lastReviewData || !lastReviewData.suggested_full_profile) return;
  copyToClipboard(e.currentTarget, wholeProfileCopyText(lastReviewData.suggested_full_profile), null);
});

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
function copyToClipboard(btn, text, fallbackTarget) {
  const original = btn.textContent;
  navigator.clipboard
    .writeText(text)
    .then(() => {
      btn.textContent = "Copied!";
      setTimeout(() => (btn.textContent = original), 1500);
    })
    .catch(() => {
      if (fallbackTarget) {
        const range = document.createRange();
        range.selectNodeContents(fallbackTarget);
        const selection = window.getSelection();
        selection.removeAllRanges();
        selection.addRange(range);
      }
      btn.textContent = fallbackTarget ? "Selected \u2014 press Ctrl+C" : "Couldn't copy \u2014 select the text instead";
      setTimeout(() => (btn.textContent = original), 2500);
    });
}

document.getElementById("step-results").addEventListener("click", (e) => {
  const btn = e.target.closest(".copy-btn");
  if (!btn) return;
  if (btn.dataset.copyText !== undefined) {
    copyToClipboard(btn, btn.dataset.copyText, null);
    return;
  }
  const target = document.getElementById(btn.dataset.copyTarget);
  if (!target) return;
  copyToClipboard(btn, target.textContent, target);
});

// --- Compare with the signed-in person's Career Profile skills -------------
// The public review can't know who is looking, and sign-in tokens are never kept
// in the browser (see career/js/auth.js), so this section asks for a sign-in
// and holds the token in memory only. Nothing is added to the profile unless
// the person leaves it ticked and presses the button.
let compareToken = null;

function resetCompare() {
  document.getElementById("compare-results").hidden = true;
  document.getElementById("compare-error").hidden = true;
  document.getElementById("compare-add-msg").hidden = true;
  document.getElementById("compare-profile-list").textContent = "";
}

async function runCompare() {
  const res = await fetch("/api/career/linkedin-skill-compare", {
    method: "POST",
    headers: { "Content-Type": "application/json", Authorization: "Bearer " + compareToken },
    body: JSON.stringify({ review: lastReviewData }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || `Request failed (${res.status})`);
  }
  const data = await res.json();

  const linkedinList = document.getElementById("compare-linkedin-list");
  const copyBtn = document.getElementById("compare-copy-btn");
  const missingOnLinkedin = data.in_profile_not_on_linkedin || [];
  linkedinList.textContent = missingOnLinkedin.length ? missingOnLinkedin.join(", ") : "Nothing: every skill in your Career Profile shows up in your LinkedIn review.";
  copyBtn.hidden = missingOnLinkedin.length === 0;

  const pickList = document.getElementById("compare-profile-list");
  pickList.textContent = "";
  const fresh = data.on_review_not_in_profile || [];
  for (const name of fresh) {
    const li = document.createElement("li");
    const label = document.createElement("label");
    const box = document.createElement("input");
    box.type = "checkbox";
    box.checked = true;
    box.dataset.skill = name;
    label.appendChild(box);
    label.appendChild(document.createTextNode(" " + name));
    li.appendChild(label);
    pickList.appendChild(li);
  }
  document.getElementById("compare-add-btn").hidden = fresh.length === 0;
  if (!fresh.length) {
    const li = document.createElement("li");
    li.textContent = "Nothing new: your Career Profile already has the skills your LinkedIn shows.";
    pickList.appendChild(li);
  }
  document.getElementById("compare-results").hidden = false;
}

document.getElementById("compare-signin-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const btn = document.getElementById("compare-signin-btn");
  const errorEl = document.getElementById("compare-error");
  errorEl.hidden = true;
  if (!lastReviewData) return;
  btn.disabled = true;
  try {
    const { accessToken } = await signIn(
      document.getElementById("compare-email").value.trim(),
      document.getElementById("compare-password").value
    );
    compareToken = accessToken;
    document.getElementById("compare-password").value = "";
    await runCompare();
  } catch (err) {
    showError(errorEl, (err && err.message) || "Couldn't sign in or compare. Please try again.");
  } finally {
    btn.disabled = false;
  }
});

document.getElementById("compare-add-btn").addEventListener("click", async () => {
  const msg = document.getElementById("compare-add-msg");
  const btn = document.getElementById("compare-add-btn");
  btn.disabled = true;
  let added = 0;
  try {
    for (const box of document.querySelectorAll("#compare-profile-list input[type=checkbox]")) {
      if (!box.checked) continue;
      const res = await fetch("/api/career/skills", {
        method: "POST",
        headers: { "Content-Type": "application/json", Authorization: "Bearer " + compareToken },
        body: JSON.stringify({ name: box.dataset.skill, source_text: null, experience_id: null }),
      });
      if (res.ok) {
        added += 1;
        // Added skills leave the list so nothing looks unfinished or broken.
        box.closest("li").remove();
      }
    }
    const remaining = document.querySelectorAll("#compare-profile-list input[type=checkbox]").length;
    if (added && remaining === 0) {
      btn.hidden = true;
      msg.textContent = added + (added === 1 ? " skill" : " skills") + " added to your Career Profile. Nothing left to add.";
    } else {
      msg.textContent = added ? added + (added === 1 ? " skill" : " skills") + " added to your Career Profile. The rest are still waiting for your tick." : "Nothing was ticked.";
    }
  } finally {
    msg.hidden = false;
    btn.disabled = false;
  }
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
