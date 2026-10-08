// Languages on the Career Profile (Phase 2C): the list inside the My Career card's
// "Languages" tile, using the same Edit/Delete card editor as Roles and Skills.
// Relies on authedFetch(), formatErrorDetail(), renderDetailCard() and
// updateDashboardSummary() from login.js. Backed by /api/career/languages.

let allLanguages = [];

function languageLabel(entry) {
  return entry.name + (entry.proficiency ? " — " + entry.proficiency : "");
}

const LANGUAGE_FIELD_DEFS = {
  card: {
    kind: "language",
    tone: "pink",
    typeLabel: "Language",
    title: (e) => e.name,
    lines: (e) => [e.proficiency],
    footer: (e) => (e.created_at ? "Added " + shortDate(e.created_at) : ""),
  },
  summary: languageLabel,
  fields: [
    { key: "name", label: "Language" },
    { key: "proficiency", label: "Proficiency (optional)" },
  ],
};

// What the API accepts: only these two fields, never an id or owner.
function languagePayload(draft) {
  return { name: (draft.name || "").trim(), proficiency: (draft.proficiency || "").trim() || null };
}

async function loadLanguages() {
  const container = document.getElementById("language-detail-list");
  allLanguages = [];
  let loadError = null;
  try {
    const res = await authedFetch("/api/career/languages");
    if (res.ok) {
      const data = await res.json();
      if (Array.isArray(data)) allLanguages = data;
    } else {
      loadError = "Languages couldn't be loaded right now.";
    }
  } catch (err) {
    loadError = "Languages couldn't be loaded right now.";
  }

  container.textContent = "";
  if (loadError) {
    const p = document.createElement("p");
    p.className = "hint";
    p.textContent = loadError;
    container.appendChild(p);
  } else if (allLanguages.length === 0) {
    const p = document.createElement("p");
    p.className = "hint";
    p.textContent = "No languages added yet.";
    container.appendChild(p);
  } else {
    for (const entry of allLanguages) {
      renderDetailCard(container, entry, LANGUAGE_FIELD_DEFS, {
        onSave: async (entity, draft) => {
          const res = await authedFetch("/api/career/languages/" + entity.id, {
            method: "PUT",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(languagePayload(draft)),
          });
          if (!res.ok) {
            const body = await res.json().catch(() => ({}));
            throw new Error(formatErrorDetail(body.detail, "Couldn't save that change."));
          }
          await loadLanguages();
        },
        onDelete: async (entity) => {
          await authedFetch("/api/career/languages/" + entity.id, { method: "DELETE" });
          await loadLanguages();
        },
      });
    }
  }
  updateDashboardSummary();
}

if (typeof document !== "undefined" && document.getElementById("language-form")) {
  document.getElementById("language-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const errorEl = document.getElementById("language-error");
    const btn = document.getElementById("language-submit-btn");
    errorEl.hidden = true;
    btn.disabled = true;
    try {
      const res = await authedFetch("/api/career/languages", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(languagePayload({
          name: document.getElementById("language-name").value,
          proficiency: document.getElementById("language-proficiency").value,
        })),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(formatErrorDetail(body.detail, "Couldn't add that language."));
      }
      document.getElementById("language-form").reset();
      await loadLanguages();
    } catch (err) {
      errorEl.textContent = (err && err.message) || "Couldn't add that language.";
      errorEl.hidden = false;
    } finally {
      btn.disabled = false;
    }
  });
}
