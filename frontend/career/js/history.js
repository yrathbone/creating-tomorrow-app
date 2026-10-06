// Read-only history of past job/skill scans and past resumes built through
// the Career Profile - a log, not an editable entity, so these cards are
// Delete-only (no renderDetailCard edit-in-place). Relies on authedFetch()/
// formatErrorDetail()/escapeHtml() from login.js/resumeReview.js, both
// loaded before this file.

// Populated by loadScanHistory() - exposed as a shared global (same
// pattern as allExperiences/allSkills in login.js) so jobMatch.js can find
// the most recent job_comparison entry to restore "Current Job Target" on
// page load, without a second fetch.
let allScanHistory = [];
let allResumeVersions = [];

async function loadScanHistory() {
  const res = await authedFetch("/api/career/scan-history");
  const entries = await res.json();
  const list = Array.isArray(entries) ? entries : [];
  allScanHistory = list;
  if (typeof updateDashboardSummary === "function") updateDashboardSummary();

  const container = document.getElementById("scan-history-list");
  if (!container) return;
  container.textContent = "";

  if (list.length === 0) {
    const p = document.createElement("p");
    p.className = "hint";
    p.textContent = "No job or skill scans yet.";
    container.appendChild(p);
    return;
  }

  for (const entry of list) {
    const card = document.createElement("div");
    card.className = "entry-summary-card";

    const header = document.createElement("div");
    header.className = "entry-summary-header";

    const title = document.createElement("strong");
    title.textContent = entry.scan_type === "job_comparison" ? (entry.job_title || "Job Comparison") : "Skill Scan";
    header.appendChild(title);

    const actions = document.createElement("span");
    actions.className = "list-row-actions";

    if (entry.scan_type === "job_comparison") {
      const matchLevel = ((entry.result_data || {}).match_report || {}).match_level || "";
      if (matchLevel) {
        const badge = document.createElement("span");
        badge.className = "history-match-badge match-level-" + matchLevel.toLowerCase();
        badge.textContent = matchLevel;
        actions.appendChild(badge);
      }
    }

    const deleteBtn = document.createElement("button");
    deleteBtn.type = "button";
    deleteBtn.className = "entry-remove-btn";
    deleteBtn.textContent = "Delete";
    deleteBtn.addEventListener("click", async () => {
      await authedFetch("/api/career/scan-history/" + entry.id, { method: "DELETE" });
      await loadScanHistory();
    });
    actions.appendChild(deleteBtn);

    header.appendChild(actions);
    card.appendChild(header);

    const summary = document.createElement("p");
    summary.className = "hint";
    summary.style.whiteSpace = "pre-line";
    summary.textContent = entry.summary_text || "";
    card.appendChild(summary);

    const date = document.createElement("p");
    date.className = "hint";
    date.textContent = entry.created_at ? new Date(entry.created_at).toLocaleDateString() : "";
    card.appendChild(date);

    container.appendChild(card);
  }
}

async function loadResumeVersions() {
  const res = await authedFetch("/api/career/resume-versions");
  const entries = await res.json();
  const list = Array.isArray(entries) ? entries : [];
  allResumeVersions = list;
  if (typeof updateDashboardSummary === "function") updateDashboardSummary();

  const container = document.getElementById("resume-version-list");
  if (!container) return;
  container.textContent = "";

  if (list.length === 0) {
    const p = document.createElement("p");
    p.className = "hint";
    p.textContent = "No resumes built yet.";
    container.appendChild(p);
    return;
  }

  for (const entry of list) {
    const data = entry.resume_data || {};
    const card = document.createElement("div");
    card.className = "entry-summary-card";

    const header = document.createElement("div");
    header.className = "entry-summary-header";

    const title = document.createElement("strong");
    title.textContent = (data.name || "Resume") + (data.headline ? " — " + data.headline : "");
    header.appendChild(title);

    const actions = document.createElement("span");
    actions.className = "list-row-actions";

    const downloadBtn = document.createElement("button");
    downloadBtn.type = "button";
    downloadBtn.className = "entry-remove-btn";
    downloadBtn.textContent = "Download again";
    downloadBtn.addEventListener("click", async () => {
      try {
        const dlRes = await authedFetch("/api/career/resume-versions/" + entry.id + "/download");
        if (!dlRes.ok) {
          const err = await dlRes.json().catch(() => ({}));
          throw new Error(formatErrorDetail(err.detail, `Request failed (${dlRes.status})`));
        }
        const blob = await dlRes.blob();
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = (data.name || "Resume").replace(/\s+/g, "_") + "_Resume.docx";
        document.body.appendChild(a);
        a.click();
        a.remove();
        URL.revokeObjectURL(url);
      } catch (err) {
        alert(err.message || "Something went wrong downloading your resume. Please try again.");
      }
    });
    actions.appendChild(downloadBtn);

    const deleteBtn = document.createElement("button");
    deleteBtn.type = "button";
    deleteBtn.className = "entry-remove-btn";
    deleteBtn.textContent = "Delete";
    deleteBtn.addEventListener("click", async () => {
      await authedFetch("/api/career/resume-versions/" + entry.id, { method: "DELETE" });
      await loadResumeVersions();
    });
    actions.appendChild(deleteBtn);

    header.appendChild(actions);
    card.appendChild(header);

    const date = document.createElement("p");
    date.className = "hint";
    date.textContent = entry.created_at ? new Date(entry.created_at).toLocaleDateString() : "";
    card.appendChild(date);

    container.appendChild(card);
  }
}
