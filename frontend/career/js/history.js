// Past job/skill scans and past resumes built through the Career Profile - a log, not an
// editable entity, so these cards are Delete-only (no renderDetailCard edit-in-place).
// Shown as visual card grids: each scan is a card with a fit-coloured top edge, each resume
// a small "document" card that says what it was tailored to. Relies on authedFetch()/
// formatErrorDetail()/escapeHtml() from login.js/resumeReview.js, both loaded before this file.

// Populated by loadScanHistory() - exposed as a shared global (same
// pattern as allExperiences/allSkills in login.js) so jobMatch.js can find
// the most recent job_comparison entry to restore "Current Job Target" on
// page load, without a second fetch.
let allScanHistory = [];
let allResumeVersions = [];
let scansLoaded = false;
let resumesLoaded = false;

// "all" | "job_comparison" | "skill_scan": remembered for this tab only.
let scanFilter = "all";

// The resume layouts the server knows (see TEMPLATES in backend/resume_builder.py).
const RESUME_LAYOUTS = [
  ["classic", "Classic: centered, shaded headings"],
  ["modern", "Modern: clean, left-aligned"],
  ["traditional", "Traditional: serif, conservative"],
];

// ---- pure helpers (unit-tested) -------------------------------------------------------

// How a scan should look: a tone (colour), the big badge text and a short type label.
// Job comparisons take their tone from the fit letter, else from the match level.
function scanCardInfo(entry) {
  if (!entry || entry.scan_type !== "job_comparison") {
    return { kind: "skill_scan", tone: "skill", badge: "Skills", typeLabel: "Skill scan", title: "Skill Scan" };
  }
  const data = entry.result_data || {};
  const fit = data.job_fit;
  const level = String((data.match_report || {}).match_level || "").toLowerCase();
  let tone = "neutral";
  let badge = "";
  if (fit && fit.letter) {
    badge = "Fit " + fit.letter;
    tone = { a: "strong", b: "good", c: "fair", d: "low" }[String(fit.letter).toLowerCase()] || "neutral";
  } else if (level) {
    badge = level.charAt(0).toUpperCase() + level.slice(1);
    tone = { high: "strong", strong: "strong", good: "good", average: "fair", moderate: "fair", fair: "fair", low: "low", weak: "low" }[level] || "neutral";
  }
  return { kind: "job_comparison", tone, badge, typeLabel: "Job comparison", title: entry.job_title || "Job Comparison" };
}

function filterScans(entries, filter) {
  const list = Array.isArray(entries) ? entries : [];
  return filter === "job_comparison" || filter === "skill_scan" ? list.filter((e) => (e.scan_type === "job_comparison" ? "job_comparison" : "skill_scan") === filter) : list;
}

// A resume card's wording: tailored resumes name the job they were built for.
function resumeCardInfo(entry, scans) {
  const data = (entry && entry.resume_data) || {};
  const scan = entry && entry.scan_history_id ? (scans || []).find((s) => s.id === entry.scan_history_id) : null;
  const jobTitle = scan && scan.job_title ? scan.job_title : null;
  return {
    title: data.name || "Resume",
    headline: data.headline || "",
    kind: entry && entry.scan_history_id ? "tailored" : "general",
    subtitle: entry && entry.scan_history_id ? (jobTitle ? "Tailored to " + jobTitle : "Tailored to a job") : "General resume",
  };
}

// ---- scans ------------------------------------------------------------------------------

async function loadScanHistory() {
  const res = await authedFetch("/api/career/scan-history");
  const entries = await res.json();
  allScanHistory = Array.isArray(entries) ? entries : [];
  scansLoaded = true;
  if (typeof updateDashboardSummary === "function") updateDashboardSummary();
  renderScanCards();
  if (resumesLoaded) renderResumeCards(); // resume cards name the job from the scan
}

function renderScanFilter() {
  const bar = document.getElementById("scan-filter");
  if (!bar) return;
  const jobs = filterScans(allScanHistory, "job_comparison").length;
  const skills = filterScans(allScanHistory, "skill_scan").length;
  bar.hidden = jobs === 0 || skills === 0; // nothing to filter between
  bar.textContent = "";
  const options = [["all", "All", allScanHistory.length], ["job_comparison", "Job comparisons", jobs], ["skill_scan", "Skill scans", skills]];
  for (const [value, label, count] of options) {
    const chip = visualButton(label + " " + count, "vis-chip btn-secondary", () => {
      scanFilter = value;
      renderScanCards();
    });
    chip.setAttribute("aria-pressed", String(scanFilter === value));
    bar.appendChild(chip);
  }
}

function renderScanCards() {
  const container = document.getElementById("scan-history-list");
  if (!container) return;
  container.textContent = "";
  if (scanFilter !== "all" && filterScans(allScanHistory, scanFilter).length === 0) scanFilter = "all";
  renderScanFilter();

  if (allScanHistory.length === 0) {
    const p = document.createElement("p");
    p.className = "hint";
    p.textContent = "No job or skill scans yet.";
    container.appendChild(p);
    return;
  }

  const grid = document.createElement("div");
  grid.className = "vis-grid";
  for (const entry of filterScans(allScanHistory, scanFilter)) {
    const info = scanCardInfo(entry);
    const fit = (entry.result_data || {}).job_fit;
    grid.appendChild(buildVisualCard({
      kind: info.kind,
      tone: info.tone,
      typeLabel: info.typeLabel,
      badge: info.badge,
      badgeTitle: fit && fit.title ? fit.title + (fit.band ? " (" + fit.band + ")" : "") : "",
      title: info.title,
      summary: entry.summary_text || "",
      footerText: shortDate(entry.created_at),
      actions: [visualButton("Delete", "entry-remove-btn", async () => {
        await authedFetch("/api/career/scan-history/" + entry.id, { method: "DELETE" });
        await loadScanHistory();
      })],
    }));
  }
  container.appendChild(grid);
}

// ---- resumes ----------------------------------------------------------------------------

async function loadResumeVersions() {
  const res = await authedFetch("/api/career/resume-versions");
  const entries = await res.json();
  allResumeVersions = Array.isArray(entries) ? entries : [];
  resumesLoaded = true;
  if (typeof updateDashboardSummary === "function") updateDashboardSummary();
  renderResumeCards();
}

async function downloadResumeVersion(entry, name, template) {
  try {
    const dlRes = await authedFetch("/api/career/resume-versions/" + entry.id + "/download?template=" + encodeURIComponent(template || "classic"));
    if (!dlRes.ok) {
      const err = await dlRes.json().catch(() => ({}));
      throw new Error(formatErrorDetail(err.detail, `Request failed (${dlRes.status})`));
    }
    const blob = await dlRes.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = (name || "Resume").replace(/\s+/g, "_") + "_Resume.docx";
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  } catch (err) {
    alert(err.message || "Something went wrong downloading your resume. Please try again.");
  }
}

function renderResumeCards() {
  const container = document.getElementById("resume-version-list");
  if (!container) return;
  container.textContent = "";

  if (allResumeVersions.length === 0) {
    const p = document.createElement("p");
    p.className = "hint";
    p.textContent = "No resumes built yet.";
    container.appendChild(p);
    return;
  }

  const grid = document.createElement("div");
  grid.className = "vis-grid";
  for (const entry of allResumeVersions) {
    const info = resumeCardInfo(entry, allScanHistory);
    const layout = document.createElement("select");
    layout.className = "vcard-select";
    layout.setAttribute("aria-label", "Layout for " + info.title);
    for (const [value, label] of RESUME_LAYOUTS) {
      const opt = document.createElement("option");
      opt.value = value;
      opt.textContent = label;
      layout.appendChild(opt);
    }
    if (typeof preferredResumeLayout !== "undefined") layout.value = preferredResumeLayout;
    const makeDefault = visualButton("Make default", "btn-secondary vcard-btn", async () => {
      const status = document.getElementById("resume-layout-status");
      makeDefault.disabled = true;
      makeDefault.textContent = "Saving...";
      const result = typeof savePreferredLayout === "function" ? await savePreferredLayout(layout.value) : { ok: false, message: "Couldn't save that right now." };
      if (status) {
        status.textContent = result.ok ? layoutSavedMessage(result.layout) : result.message;
        status.hidden = false;
      }
      if (!result.ok) syncDefault();
    });
    // the button says so when the menu already shows the saved default
    const syncDefault = () => {
      const isDefault = typeof preferredResumeLayout !== "undefined" && layout.value === preferredResumeLayout;
      makeDefault.textContent = isDefault ? "✓ Your default" : "Make default";
      makeDefault.disabled = isDefault;
    };
    layout.addEventListener("change", syncDefault);
    syncDefault();
    grid.appendChild(buildVisualCard({
      kind: "resume",
      tone: info.kind === "tailored" ? "fair" : "good",
      typeLabel: info.kind === "tailored" ? "Tailored resume" : "General resume",
      title: info.title + (info.headline ? " — " + info.headline : ""),
      lines: [info.subtitle],
      extra: [layout],
      footerText: "Built " + shortDate(entry.created_at),
      actions: [
        visualButton("Download again", "btn-secondary vcard-btn", () => downloadResumeVersion(entry, (entry.resume_data || {}).name, layout.value)),
        makeDefault,
        visualButton("Delete", "entry-remove-btn", async () => {
          await authedFetch("/api/career/resume-versions/" + entry.id, { method: "DELETE" });
          await loadResumeVersions();
        }),
      ],
    }));
  }
  container.appendChild(grid);
}
