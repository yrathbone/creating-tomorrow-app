// The preferred resume layout (saved on the Career Profile, migration 0009): pick it once and every
// layout menu on the dashboard starts on it. A menu can still be changed for one download.
// Relies on authedFetch()/formatErrorDetail() from login.js. If the server's upgrade has not been
// applied yet, everything quietly stays on Classic and saving says so.

let preferredResumeLayout = "classic";

const RESUME_LAYOUT_NAMES = { classic: "Classic", modern: "Modern", traditional: "Traditional" };

// Pure helpers (unit-tested)
function normalizeResumeLayout(value) {
  return Object.prototype.hasOwnProperty.call(RESUME_LAYOUT_NAMES, value) ? value : "classic";
}

function layoutSavedMessage(layout) {
  return "Saved. Your resumes will start on " + RESUME_LAYOUT_NAMES[normalizeResumeLayout(layout)] + " from now on.";
}

// Every menu marked data-resume-layout shows the saved choice.
function applyPreferredLayout() {
  if (typeof document === "undefined") return;
  document.querySelectorAll("select[data-resume-layout]").forEach((sel) => { sel.value = preferredResumeLayout; });
  if (typeof renderResumeCards === "function" && typeof resumesLoaded !== "undefined" && resumesLoaded) renderResumeCards();
}

async function loadResumeLayoutPreference() {
  try {
    const res = await authedFetch("/api/career/resume-layout");
    if (res.ok) {
      const data = await res.json();
      preferredResumeLayout = normalizeResumeLayout(data.layout);
    }
  } catch (err) {
    // A convenience only: stay on Classic and never block the dashboard.
  }
  applyPreferredLayout();
}

// Resolves { ok: true, layout } or { ok: false, message }.
async function savePreferredLayout(layout) {
  const wanted = normalizeResumeLayout(layout);
  try {
    const res = await authedFetch("/api/career/resume-layout", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ layout: wanted }),
    });
    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      return { ok: false, message: typeof body.detail === "string" ? body.detail : "Couldn't save that right now." };
    }
    const data = await res.json();
    preferredResumeLayout = normalizeResumeLayout(data.layout);
    applyPreferredLayout();
    return { ok: true, layout: preferredResumeLayout };
  } catch (err) {
    return { ok: false, message: (err && err.message) || "Couldn't save that right now." };
  }
}

// "Make this my default" buttons next to the download menus.
if (typeof document !== "undefined") {
  document.querySelectorAll("[data-layout-default]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const select = document.getElementById(btn.dataset.layoutDefault);
      const msg = document.getElementById(btn.dataset.layoutMsg);
      if (!select) return;
      btn.disabled = true;
      const result = await savePreferredLayout(select.value);
      btn.disabled = false;
      if (msg) {
        msg.textContent = result.ok ? layoutSavedMessage(result.layout) : result.message;
        msg.hidden = false;
      }
    });
  });
}
