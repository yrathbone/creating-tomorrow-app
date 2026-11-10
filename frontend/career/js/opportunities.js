// My Opportunities (C-52 MVP-0): job links the member saves themselves.
// The server never fetches a link. This file only shows what the member saved.
// Relies on authedFetch()/formatErrorDetail() from login.js and, when present,
// loadApplications()/openSnapshotPanel() from the tracker and snapshot code.
// Feature switch: the server answers 404 while CT_OPPORTUNITIES_ENABLED is off,
// and the card stays hidden. Every piece of text is written with textContent.

let allOpportunities = [];
let resumeVersionOptions = [];

const OPPORTUNITY_STATE_LABELS = { saved: "Saved", dismissed: "Dismissed", applied: "Applied" };
const OPPORTUNITY_PERIOD_LABELS = { hourly: "per hour", annual: "per year" };
const OPPORTUNITY_APPROVAL_LABELS = {
  current: "Résumé approved for this job",
  changed_since_approval: "Résumé changed since you approved it: approve again",
  version_removed: "The approved résumé was deleted: choose another",
};

// Returns the URL as text only when it is an https link with no credentials; otherwise null.
function safeHttpsHref(raw) {
  try {
    const u = new URL(String(raw || ""));
    if (u.protocol !== "https:" || u.username || u.password) return null;
    return u.href;
  } catch (err) {
    return null;
  }
}

// The body for PUT /api/career/opportunities/{id}. The server replaces every field it is
// sent, so each update carries the stored values unchanged, plus the overrides.
// state is left out unless overridden, so an 'applied' link keeps its state.
function buildUpdatePayload(item, overrides = {}) {
  const base = item.base || {};
  const approval = item.approval || null;
  const payload = {
    title: item.title,
    employer: item.employer ?? null,
    job_url: item.job_url,
    location_text: item.location_text ?? null,
    work_arrangement: item.work_arrangement ?? null,
    employment_type: item.employment_type ?? null,
    base_min: base.min ?? null,
    base_max: base.max ?? null,
    base_period: base.period ?? null,
    pay_note: item.pay_note ?? null,
    notes: item.notes ?? null,
    last_verified_on: item.last_verified_on ?? null,
    follow_up_on: item.follow_up_on ?? null,
    approved_resume_version_id: approval && approval.status !== "version_removed" ? approval.version_id : null,
    dismiss_reason: item.state === "dismissed" ? (item.dismiss_reason ?? null) : null,
  };
  return Object.assign(payload, overrides);
}

// Turns an error response into a sentence. The server sends either a string or {message}.
async function readOpportunityError(res, fallback) {
  let body = null;
  try { body = await res.json(); } catch (err) { body = null; }
  const detail = body && body.detail;
  if (detail && typeof detail === "object" && typeof detail.message === "string") return detail.message;
  return formatErrorDetail(detail, fallback);
}

function setOpportunityStatus(text) {
  const el = document.getElementById("opportunities-status");
  if (el) el.textContent = text || "";
}

// Loads the list. The card stays hidden unless the server answers, which is how a switched-off feature stays invisible.
async function loadOpportunities() {
  const card = document.getElementById("opportunities-card");
  if (!card) return;
  let res;
  try {
    res = await authedFetch("/api/career/opportunities");
  } catch (err) {
    card.hidden = true;
    return;
  }
  if (!res.ok) {
    card.hidden = true;
    return;
  }
  allOpportunities = await res.json();
  card.hidden = false;
  await loadResumeVersionOptions();
  renderOpportunities();
}

async function loadResumeVersionOptions() {
  try {
    const res = await authedFetch("/api/career/resume-versions");
    resumeVersionOptions = res.ok ? await res.json() : [];
  } catch (err) {
    resumeVersionOptions = [];
  }
}

function renderOpportunities() {
  const list = document.getElementById("opportunity-list");
  const empty = document.getElementById("opportunity-empty");
  const trackerBtn = document.getElementById("opportunities-tracker-btn");
  if (!list) return;
  list.textContent = "";
  if (empty) empty.hidden = allOpportunities.length > 0;
  for (const item of allOpportunities) list.appendChild(buildOpportunityItem(item));
  if (trackerBtn) trackerBtn.hidden = !allOpportunities.some((o) => o.state === "applied");
}

function makeButton(label, onClick, className) {
  const btn = document.createElement("button");
  btn.type = "button";
  btn.textContent = label;
  if (className) btn.className = className;
  btn.addEventListener("click", onClick);
  return btn;
}

function buildOpportunityItem(item) {
  const li = document.createElement("li");
  li.className = "opportunity-item";

  const heading = document.createElement("p");
  const title = document.createElement("strong");
  title.textContent = item.title;
  heading.appendChild(title);
  if (item.employer) heading.appendChild(document.createTextNode(" at " + item.employer));
  li.appendChild(heading);

  const meta = document.createElement("p");
  meta.className = "hint";
  const parts = [OPPORTUNITY_STATE_LABELS[item.state] || item.state];
  if (item.source) parts.push(item.source);
  if (item.location_text) parts.push(item.location_text);
  meta.textContent = parts.join(" · ");
  li.appendChild(meta);

  if (item.application_removed) {
    const note = document.createElement("p");
    note.className = "hint";
    note.textContent = "The application linked to this job was removed from your tracker. Record it again if you applied.";
    li.appendChild(note);
  }

  const href = safeHttpsHref(item.job_url);
  if (href) {
    const link = document.createElement("a");
    link.href = href;
    link.target = "_blank";
    link.rel = "noopener noreferrer nofollow";
    link.textContent = "Open the posting on the employer’s site";
    li.appendChild(link);
  }

  if (item.base) {
    const pay = document.createElement("p");
    pay.className = "hint";
    const low = item.base.min ?? "";
    const high = item.base.max ?? "";
    const range = low !== "" && high !== "" ? low + "–" + high : String(low !== "" ? low : high);
    pay.textContent = "Guaranteed base: " + range + " " + (OPPORTUNITY_PERIOD_LABELS[item.base.period] || "") + ". " + item.base_note;
    li.appendChild(pay);
  }
  if (item.pay_note) {
    const other = document.createElement("p");
    other.className = "hint";
    other.textContent = "Other pay (not base): " + item.pay_note;
    li.appendChild(other);
  }

  if (item.state !== "dismissed" && item.approval) {
    const approval = document.createElement("p");
    approval.className = "hint";
    approval.textContent = OPPORTUNITY_APPROVAL_LABELS[item.approval.status] || "";
    li.appendChild(approval);
  }

  const notice = document.createElement("p");
  notice.className = "hint";
  notice.textContent = item.safety_notice;
  li.appendChild(notice);

  const actions = document.createElement("div");
  actions.className = "opportunity-actions";
  if (item.state !== "dismissed") {
    actions.appendChild(makeButton("Use for comparison", () => useForComparison(item), "btn-secondary"));
  }
  if (item.state !== "applied" && item.state !== "dismissed") {
    actions.appendChild(makeButton("I applied: add to my tracker", () => recordApplication(item), "btn-gold"));
  }
  // A link whose application was removed is still stored as applied, and the server will not change that from here.
  if (item.state === "saved" && !item.application_removed) {
    actions.appendChild(makeButton("Dismiss", () => sendUpdate(item, { state: "dismissed", dismiss_reason: "other" }), "btn-secondary"));
  } else if (item.state === "dismissed") {
    actions.appendChild(makeButton("Restore", () => sendUpdate(item, { state: "saved" }), "btn-secondary"));
  }
  actions.appendChild(makeButton("Delete", () => deleteOpportunity(item), "btn-secondary"));
  li.appendChild(actions);

  if (item.state !== "dismissed" && resumeVersionOptions.length) {
    li.appendChild(buildApprovalControls(item));
  }
  return li;
}

function buildApprovalControls(item) {
  const wrap = document.createElement("div");
  wrap.className = "opportunity-approval";
  const label = document.createElement("label");
  label.className = "field";
  const span = document.createElement("span");
  span.textContent = "Résumé to use for this job";
  const select = document.createElement("select");
  for (const v of resumeVersionOptions) {
    const option = document.createElement("option");
    option.value = String(v.id);
    option.textContent = "Résumé saved " + (v.created_at ? v.created_at.slice(0, 10) : "");
    if (item.approval && item.approval.version_id === v.id && item.approval.status !== "version_removed") option.selected = true;
    select.appendChild(option);
  }
  label.appendChild(span);
  label.appendChild(select);
  wrap.appendChild(label);
  wrap.appendChild(makeButton("Approve this résumé for this job", () => approveResume(item, Number(select.value)), "btn-secondary"));
  return wrap;
}

// Puts the saved job's title and employer in front of the member. The existing compare flow
// is used as it is: no new AI call, and no opportunity id is sent to it.
function useForComparison(item) {
  const note = document.getElementById("opportunities-context");
  if (note) {
    note.hidden = false;
    note.textContent = "Comparing with: " + item.title + (item.employer ? " at " + item.employer : "")
      + ". Paste that job’s description in Discover Your Fit above to compare.";
  }
  const addBtn = document.getElementById("job-target-add-btn");
  if (addBtn) addBtn.focus();
}

// Saves a field change. Returns the updated item, or null after showing the error.
async function sendUpdate(item, overrides) {
  const res = await authedFetch("/api/career/opportunities/" + item.id, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(buildUpdatePayload(item, overrides)),
  });
  if (!res.ok) {
    setOpportunityStatus(await readOpportunityError(res, "That change was not saved."));
    return null;
  }
  const updated = await res.json();
  allOpportunities = allOpportunities.map((o) => (o.id === updated.id ? updated : o));
  renderOpportunities();
  return updated;
}

// Approves one résumé version for this job. Approving the same version again after it changed
// needs two saves: clear the approval, then approve it, which takes a fresh fingerprint.
async function approveResume(item, versionId) {
  if (!Number.isInteger(versionId)) return null;
  let current = item;
  if (item.approval && item.approval.status === "changed_since_approval" && item.approval.version_id === versionId) {
    current = await sendUpdate(current, { approved_resume_version_id: null });
    if (!current) return null;
  }
  const done = await sendUpdate(current, { approved_resume_version_id: versionId });
  if (done) setOpportunityStatus("Résumé approved for this job.");
  return done;
}

// Records the application through the server, which is retry-safe. Shows the tracker link afterwards.
async function recordApplication(item) {
  const res = await authedFetch("/api/career/opportunities/" + item.id + "/record-application", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({}),
  });
  if (!res.ok) {
    setOpportunityStatus(await readOpportunityError(res, "The application was not recorded."));
    return;
  }
  const body = await res.json();
  allOpportunities = allOpportunities.map((o) => (o.id === body.opportunity.id ? body.opportunity : o));
  renderOpportunities();
  setOpportunityStatus(body.already_recorded ? "This job is already in your tracker." : "Added to your tracker.");
  if (typeof loadApplications === "function") await loadApplications();
}

async function deleteOpportunity(item) {
  if (typeof window !== "undefined" && typeof window.confirm === "function" && !window.confirm("Remove this saved link? This cannot be undone.")) return;
  const res = await authedFetch("/api/career/opportunities/" + item.id, { method: "DELETE" });
  if (!res.ok) {
    setOpportunityStatus(await readOpportunityError(res, "That link was not removed."));
    return;
  }
  allOpportunities = allOpportunities.filter((o) => o.id !== item.id);
  renderOpportunities();
}

// Builds the POST body from the add form. Pay is whole numbers only; the server checks the rest.
function buildCreatePayload(fields) {
  const num = (v) => (v === "" || v == null ? null : Number(v));
  const text = (v) => (String(v || "").trim() || null);
  return {
    title: String(fields.title || "").trim(),
    employer: text(fields.employer),
    job_url: String(fields.job_url || "").trim(),
    location_text: text(fields.location_text),
    work_arrangement: text(fields.work_arrangement),
    base_min: num(fields.base_min),
    base_max: num(fields.base_max),
    base_period: text(fields.base_period),
    pay_note: text(fields.pay_note),
    notes: text(fields.notes),
  };
}

async function submitOpportunityForm(event) {
  if (event && event.preventDefault) event.preventDefault();
  const field = (id) => { const el = document.getElementById(id); return el ? el.value : ""; };
  const payload = buildCreatePayload({
    title: field("opportunity-title"),
    employer: field("opportunity-employer"),
    job_url: field("opportunity-url"),
    location_text: field("opportunity-location"),
    work_arrangement: field("opportunity-arrangement"),
    base_min: field("opportunity-base-min"),
    base_max: field("opportunity-base-max"),
    base_period: field("opportunity-base-period"),
    pay_note: field("opportunity-pay-note"),
    notes: field("opportunity-notes"),
  });
  if (!safeHttpsHref(payload.job_url)) {
    setOpportunityStatus("The job link must start with https:// and must not include a username or password.");
    return null;
  }
  for (const key of ["base_min", "base_max"]) {
    if (payload[key] !== null && !Number.isInteger(payload[key])) {
      setOpportunityStatus("Enter guaranteed base pay as whole numbers.");
      return null;
    }
  }
  const res = await authedFetch("/api/career/opportunities", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    setOpportunityStatus(await readOpportunityError(res, "That link was not saved."));
    return null;
  }
  const created = await res.json();
  allOpportunities = [created, ...allOpportunities.filter((o) => o.id !== created.id)];
  renderOpportunities();
  const form = document.getElementById("opportunity-form");
  if (form && form.reset) form.reset();
  if (form) form.hidden = true;
  setOpportunityStatus("Saved. Check the employer’s site before you share personal information.");
  return created;
}

function toggleOpportunityForm() {
  const form = document.getElementById("opportunity-form");
  if (form) form.hidden = !form.hidden;
}

function openOpportunityTracker() {
  if (typeof openSnapshotPanel === "function") openSnapshotPanel("applications", false);
}

document.addEventListener("DOMContentLoaded", () => {
  const form = document.getElementById("opportunity-form");
  if (form) form.addEventListener("submit", submitOpportunityForm);
  const toggle = document.getElementById("opportunities-add-toggle");
  if (toggle) toggle.addEventListener("click", toggleOpportunityForm);
  const cancel = document.getElementById("opportunity-cancel-btn");
  if (cancel) cancel.addEventListener("click", () => { if (form) form.hidden = true; });
  const tracker = document.getElementById("opportunities-tracker-btn");
  if (tracker) tracker.addEventListener("click", openOpportunityTracker);
});
