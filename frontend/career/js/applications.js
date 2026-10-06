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

  for (const entry of allApplications) {
    const card = document.createElement("div");
    card.className = "entry-summary-card application-card app-status-" + entry.status;

    const header = document.createElement("div");
    header.className = "entry-summary-header";
    const title = document.createElement("strong");
    title.textContent = entry.job_title + (entry.company ? " — " + entry.company : "");
    header.appendChild(title);

    const del = document.createElement("button");
    del.type = "button";
    del.className = "entry-remove-btn";
    del.textContent = "Delete";
    del.addEventListener("click", async () => {
      if (!window.confirm("Remove this application from your tracker?")) return;
      await authedFetch("/api/career/applications/" + entry.id, { method: "DELETE" });
      await loadApplications();
    });
    header.appendChild(del);
    card.appendChild(header);

    const days = daysSince(entry.applied_on);
    const when = document.createElement("p");
    when.className = "hint";
    when.textContent = "Applied " + entry.applied_on + (days !== null && days >= 0 ? " (" + (days === 0 ? "today" : days + (days === 1 ? " day ago" : " days ago")) + ")" : "");
    card.appendChild(when);

    const statusSelect = document.createElement("select");
    statusSelect.className = "application-status";
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
    card.appendChild(statusSelect);

    // Gentle nudge: still "waiting" after two weeks is worth a status update.
    if (entry.status === "applied" && days !== null && days >= 14) {
      const nudge = document.createElement("p");
      nudge.className = "hint application-nudge";
      nudge.textContent = "No word in " + days + " days? Mark it \"No response\" or follow up.";
      card.appendChild(nudge);
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
    card.appendChild(notes);

    list.appendChild(card);
  }
}

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
