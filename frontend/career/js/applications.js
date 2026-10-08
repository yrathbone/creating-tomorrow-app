// Application tracker: jobs the candidate says they applied for, with a status
// they come back and update. The app can't know when someone applies, so every
// entry is added by them: one click from the finished-resume screen
// (jobMatch.js calls addApplication) or by hand in the Applications tile.
// Relies on authedFetch()/formatErrorDetail()/updateDashboardSummary() from
// login.js. If the server's applications table doesn't exist yet (the database
// step hasn't been run), the page keeps working and the panel says so.

let allApplications = [];
let applicationsUnavailable = false;

const APPLICATION_STATUS_LABELS = {
  applied: "Applied, waiting",
  no_response: "No response",
  interview: "Interview",
  rejected: "Rejected",
  offer: "Offer",
};

// The board view: one column per status, in the order a search usually moves.
const APPLICATION_BOARD_COLUMNS = ["applied", "interview", "offer", "no_response", "rejected"];

// Pure helper (unit-tested): { status: [entries...] } with every column present, newest first.
function groupApplicationsByStatus(apps) {
  const groups = {};
  for (const status of APPLICATION_BOARD_COLUMNS) groups[status] = [];
  for (const entry of apps || []) {
    const status = groups[entry.status] ? entry.status : "applied";
    groups[status].push(entry);
  }
  for (const status of APPLICATION_BOARD_COLUMNS) {
    groups[status].sort((a, b) => String(b.applied_on || "").localeCompare(String(a.applied_on || "")));
  }
  return groups;
}

// How an application card looks (pure, unit-tested): colour by status, a short "days" badge.
const APPLICATION_TONES = { applied: "good", interview: "fair", offer: "strong", no_response: "neutral", rejected: "low" };

function applicationCardInfo(entry, now) {
  const status = APPLICATION_TONES[entry.status] ? entry.status : "applied";
  const then = new Date((entry.applied_on || "") + "T00:00:00");
  const days = isNaN(then) ? null : Math.floor(((now || Date.now()) - then.getTime()) / 86400000);
  return {
    tone: APPLICATION_TONES[status],
    typeLabel: APPLICATION_STATUS_LABELS[status],
    badge: days === null || days < 0 ? "" : days === 0 ? "Today" : days + (days === 1 ? " day" : " days"),
    days,
    stale: status === "applied" && days !== null && days >= 14,
  };
}

// List or Board: remembered for this tab only (sessionStorage, like the sign-in).
let applicationView = "list";
try {
  if (typeof sessionStorage !== "undefined" && sessionStorage.getItem("ct_application_view") === "board") applicationView = "board";
} catch (err) { /* storage blocked: stay on the list */ }

function setApplicationView(view) {
  applicationView = view === "board" ? "board" : "list";
  try { sessionStorage.setItem("ct_application_view", applicationView); } catch (err) { /* ignore */ }
  renderApplications();
}

function daysSince(isoDate) {
  const then = new Date(isoDate + "T00:00:00");
  if (isNaN(then)) return null;
  return Math.floor((Date.now() - then.getTime()) / 86400000);
}

function todayIso() {
  const d = new Date();
  const pad = (n) => String(n).padStart(2, "0");
  return d.getFullYear() + "-" + pad(d.getMonth() + 1) + "-" + pad(d.getDate());
}

async function loadApplications() {
  try {
    const res = await authedFetch("/api/career/applications");
    if (!res.ok) throw new Error("unavailable");
    const list = await res.json();
    allApplications = Array.isArray(list) ? list : [];
    applicationsUnavailable = false;
  } catch (err) {
    allApplications = [];
    applicationsUnavailable = true;
  }
  renderApplications();
  if (typeof updateDashboardSummary === "function") updateDashboardSummary();
}

async function saveApplication(entry, changes) {
  const res = await authedFetch("/api/career/applications/" + entry.id, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      job_title: entry.job_title,
      company: entry.company,
      applied_on: entry.applied_on,
      status: entry.status,
      notes: entry.notes,
      scan_history_id: entry.scan_history_id,
      resume_version_id: entry.resume_version_id,
      ...changes,
    }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(formatErrorDetail(err.detail, "Couldn't save that change."));
  }
  await loadApplications();
}

// Used by the finished-resume screen (jobMatch.js) and the manual form below.
async function addApplication(payload) {
  const res = await authedFetch("/api/career/applications", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(formatErrorDetail(err.detail, "Couldn't add that application."));
  }
  await loadApplications();
}

function renderApplications() {
  const list = document.getElementById("application-list");
  const summary = document.getElementById("application-summary");
  if (!list || !summary) return;
  list.textContent = "";
  syncApplicationViewToggle();

  if (applicationsUnavailable) {
    summary.textContent = "";
    const p = document.createElement("p");
    p.className = "hint";
    p.textContent = "The application tracker isn't switched on yet. It needs a one-time database step on the server.";
    list.appendChild(p);
    return;
  }

  const counts = {};
  for (const a of allApplications) counts[a.status] = (counts[a.status] || 0) + 1;
  summary.textContent = allApplications.length
    ? Object.keys(APPLICATION_STATUS_LABELS).filter((k) => counts[k]).map((k) => counts[k] + " " + APPLICATION_STATUS_LABELS[k].toLowerCase()).join(" · ")
    : "";

  if (allApplications.length === 0) {
    const p = document.createElement("p");
    p.className = "hint";
    p.textContent = "Nothing tracked yet. After you build a resume for a job and apply, press \"I applied for this job\" to add it here.";
    list.appendChild(p);
    return;
  }

  if (applicationView === "board") {
    renderApplicationBoard(list);
    return;
  }

  const grid = document.createElement("div");
  grid.className = "vis-grid";
  for (const entry of allApplications) grid.appendChild(buildApplicationCard(entry));
  list.appendChild(grid);
}

// One application as the shared card, plus the status menu and notes box it always had.
function buildApplicationCard(entry) {
  const info = applicationCardInfo(entry);

  const statusSelect = document.createElement("select");
  statusSelect.className = "application-status";
  statusSelect.setAttribute("aria-label", "Status for " + entry.job_title);
  for (const [value, label] of Object.entries(APPLICATION_STATUS_LABELS)) {
    const opt = document.createElement("option");
    opt.value = value;
    opt.textContent = label;
    statusSelect.appendChild(opt);
  }
  statusSelect.value = entry.status;
  statusSelect.addEventListener("change", async () => {
    statusSelect.disabled = true;
    try {
      await saveApplication(entry, { status: statusSelect.value });
    } catch (err) {
      window.alert(err.message);
      statusSelect.value = entry.status;
      statusSelect.disabled = false;
    }
  });

  const extra = [statusSelect];
  // Gentle nudge: still "waiting" after two weeks is worth a status update.
  if (info.stale) {
    const nudge = document.createElement("p");
    nudge.className = "hint application-nudge";
    nudge.textContent = "No word in " + info.days + " days? Mark it \"No response\" or follow up.";
    extra.push(nudge);
  }

  const notes = document.createElement("textarea");
  notes.className = "application-notes";
  notes.rows = 2;
  notes.placeholder = "Notes (who you spoke to, next step, date of the interview...)";
  notes.value = entry.notes || "";
  notes.addEventListener("blur", async () => {
    if ((notes.value.trim() || null) === (entry.notes || null)) return;
    try {
      await saveApplication(entry, { notes: notes.value });
    } catch (err) {
      window.alert(err.message);
    }
  });
  extra.push(notes);

  return buildVisualCard({
    kind: "application",
    tone: info.tone,
    typeLabel: info.typeLabel,
    badge: info.badge,
    title: entry.job_title,
    lines: [entry.company],
    extra,
    footerText: "Applied " + (shortDate(entry.applied_on + "T00:00:00") || entry.applied_on),
    actions: [visualButton("Delete", "entry-remove-btn", async () => {
      if (!window.confirm("Remove this application from your tracker?")) return;
      await authedFetch("/api/career/applications/" + entry.id, { method: "DELETE" });
      await loadApplications();
    })],
  });
}

// The List / Board switch is only shown when there is something to show.
function syncApplicationViewToggle() {
  const toggle = document.getElementById("application-view-toggle");
  if (!toggle) return;
  toggle.hidden = applicationsUnavailable || allApplications.length === 0;
  const listBtn = document.getElementById("application-view-list");
  const boardBtn = document.getElementById("application-view-board");
  if (listBtn) listBtn.setAttribute("aria-pressed", String(applicationView === "list"));
  if (boardBtn) boardBtn.setAttribute("aria-pressed", String(applicationView === "board"));
}

// Moves an application to another column. Used by drag and drop and by the "Move to" menu.
async function moveApplication(entry, status) {
  if (!entry || entry.status === status) return;
  try {
    await saveApplication(entry, { status });
  } catch (err) {
    window.alert(err.message);
    renderApplications();
  }
}

// Board: five columns, a card per application. Notes and Delete stay in List view.
function renderApplicationBoard(container) {
  const groups = groupApplicationsByStatus(allApplications);
  const board = document.createElement("div");
  board.className = "app-board";

  for (const status of APPLICATION_BOARD_COLUMNS) {
    const col = document.createElement("section");
    col.className = "app-col app-col-" + status;
    col.setAttribute("aria-label", APPLICATION_STATUS_LABELS[status]);

    const head = document.createElement("h4");
    head.className = "app-col-head";
    const name = document.createElement("span");
    name.textContent = APPLICATION_STATUS_LABELS[status];
    const count = document.createElement("span");
    count.className = "app-col-count";
    count.textContent = String(groups[status].length);
    head.appendChild(name);
    head.appendChild(count);
    col.appendChild(head);

    const body = document.createElement("div");
    body.className = "app-col-body";
    body.addEventListener("dragover", (e) => {
      e.preventDefault();
      body.classList.add("app-drop");
    });
    body.addEventListener("dragleave", () => body.classList.remove("app-drop"));
    body.addEventListener("drop", (e) => {
      e.preventDefault();
      body.classList.remove("app-drop");
      const id = e.dataTransfer && e.dataTransfer.getData("text/plain");
      const entry = allApplications.find((a) => String(a.id) === String(id));
      moveApplication(entry, status);
    });

    if (groups[status].length === 0) {
      const empty = document.createElement("p");
      empty.className = "app-col-empty";
      empty.textContent = "Nothing here";
      body.appendChild(empty);
    }

    for (const entry of groups[status]) {
      const card = document.createElement("article");
      card.className = "app-card";
      card.draggable = true;
      card.addEventListener("dragstart", (e) => {
        e.dataTransfer.setData("text/plain", String(entry.id));
        e.dataTransfer.effectAllowed = "move";
        card.classList.add("app-dragging");
      });
      card.addEventListener("dragend", () => card.classList.remove("app-dragging"));

      const title = document.createElement("strong");
      title.className = "app-card-title";
      title.textContent = entry.job_title;
      card.appendChild(title);

      if (entry.company) {
        const company = document.createElement("span");
        company.className = "app-card-company";
        company.textContent = entry.company;
        card.appendChild(company);
      }

      const days = daysSince(entry.applied_on);
      const when = document.createElement("span");
      when.className = "app-card-when";
      when.textContent = days !== null && days >= 0 ? (days === 0 ? "Applied today" : "Applied " + days + (days === 1 ? " day ago" : " days ago")) : "Applied " + entry.applied_on;
      card.appendChild(when);

      if (entry.status === "applied" && days !== null && days >= 14) {
        const nudge = document.createElement("span");
        nudge.className = "app-card-nudge";
        nudge.textContent = "No word in " + days + " days. Follow up?";
        card.appendChild(nudge);
      }

      // The menu does the same job as dragging: for keyboards, phones and screen readers.
      const move = document.createElement("select");
      move.className = "app-card-move";
      move.setAttribute("aria-label", "Move " + entry.job_title + " to");
      for (const s of APPLICATION_BOARD_COLUMNS) {
        const opt = document.createElement("option");
        opt.value = s;
        opt.textContent = (s === entry.status ? "" : "Move to: ") + APPLICATION_STATUS_LABELS[s];
        move.appendChild(opt);
      }
      move.value = entry.status;
      move.addEventListener("change", () => moveApplication(entry, move.value));
      card.appendChild(move);

      body.appendChild(card);
    }

    col.appendChild(body);
    board.appendChild(col);
  }

  const tip = document.createElement("p");
  tip.className = "hint app-board-tip";
  tip.textContent = "Drag a card to a new column, or use the menu on the card. Switch to List to add notes or delete an application.";
  container.appendChild(board);
  container.appendChild(tip);
}

if (typeof document !== "undefined" && document.getElementById("application-add-toggle-btn")) {
  // List / Board switch
  document.getElementById("application-view-list").addEventListener("click", () => setApplicationView("list"));
  document.getElementById("application-view-board").addEventListener("click", () => setApplicationView("board"));

  // Add by hand
  document.getElementById("application-add-toggle-btn").addEventListener("click", () => {
    const form = document.getElementById("application-form");
    form.hidden = !form.hidden;
    if (!form.hidden) {
      document.getElementById("application-date").value = todayIso();
      document.getElementById("application-title").focus();
    }
  });

  document.getElementById("application-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const errorEl = document.getElementById("application-form-error");
    errorEl.hidden = true;
    try {
      await addApplication({
        job_title: document.getElementById("application-title").value,
        company: document.getElementById("application-company").value,
        applied_on: document.getElementById("application-date").value || null,
      });
      document.getElementById("application-form").reset();
      document.getElementById("application-form").hidden = true;
    } catch (err) {
      errorEl.textContent = err.message;
      errorEl.hidden = false;
    }
  });
}
