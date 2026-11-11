// My Opportunities (C-52 MVP-0): the saved-links card. Add a job link by hand, see the saved links, check that a
// posting is still open, set a follow-up date, dismiss / restore / report a link, compare it, approve a résumé for it,
// and remove it. The server never fetches a link. Nothing here scrapes, alerts, emails or applies for a job.
// Relies on authedFetch() and formatErrorDetail() from login.js.
// Feature switch: the server answers 404 while CT_OPPORTUNITIES_ENABLED is off, and the card stays hidden.
// Every piece of saved text is written with textContent, never as markup.

let allOpportunities = [];
let showDismissedOpportunities = false;

const OPPORTUNITY_STATE_LABELS = { saved: "Saved", dismissed: "Dismissed", applied: "Applied" };
const OPPORTUNITY_PERIOD_LABELS = { hourly: "per hour", annual: "per year" };
const OPPORTUNITY_DISMISS_REASONS = [
  ["not_interested", "Not interested"],
  ["wrong_location", "Wrong location"],
  ["pay_too_low", "Pay too low"],
  ["looks_suspicious", "Looks suspicious"],
  ["other", "Other"],
];
const OPPORTUNITY_UNSUPPORTED_ADDRESS = "This web address isn’t supported yet. Please enter a standard HTTPS job link.";

// Returns the URL only when it is an https link with no username or password; otherwise null.
// Mirrors the server's rules: no local or private names, no trailing dot, no all-digit last label (IP in another notation).
const OPPORTUNITY_BLOCKED_SUFFIXES = [".local", ".internal", ".localhost", ".test", ".invalid", ".home", ".lan"];
function safeHttpsHref(raw) {
  try {
    const text = String(raw || "");
    if (/[^\x00-\x7f]/.test(text) || /%/.test(text)) return null;
    const u = new URL(text);
    if (u.protocol !== "https:" || u.username || u.password) return null;
    if (u.port && u.port !== "443") return null;
    const host = u.hostname.toLowerCase();
    if (!host || host.endsWith(".") || host.startsWith(".") || host.indexOf("..") !== -1) return null;
    if (host.indexOf(".") === -1 || host === "localhost") return null;
    if (OPPORTUNITY_BLOCKED_SUFFIXES.some((s) => host.endsWith(s))) return null;
    if (/^(0x[0-9a-f]*|[0-9]+)$/i.test(host.split(".").pop())) return null;
    if (host.charAt(0) === "[") return null;
    return u.href;
  } catch (err) {
    return null;
  }
}

// The same message the server gives for a web address it does not support (Unicode or percent-encoded host names).
function opportunityLinkProblem(raw) {
  const text = String(raw || "").trim();
  if (!/^https:\/\//i.test(text)) return "The job link must start with https:// and must not include a username or password.";
  if (/[^\x00-\x7f]/.test(text) || /%/.test(text.replace(/^https:\/\//i, "").split("/")[0])) return OPPORTUNITY_UNSUPPORTED_ADDRESS;
  if (!safeHttpsHref(text)) return "The job link must start with https:// and must not include a username or password.";
  return null;
}

// Body for POST /api/career/opportunities. Pay is whole numbers only; the server checks the rest.
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

// Body for PUT /api/career/opportunities/{id}: the whole saved link as the server returned it, with the changes applied.
// The approval is never sent (it has its own route). A recorded application keeps its state: 'applied' is not sent.
function buildUpdatePayload(item, changes) {
  const base = item.base || {};
  const body = {
    title: item.title,
    employer: item.employer || null,
    job_url: item.job_url,
    location_text: item.location_text || null,
    work_arrangement: item.work_arrangement || null,
    employment_type: item.employment_type || null,
    base_min: base.min ?? null,
    base_max: base.max ?? null,
    base_period: base.period || null,
    pay_note: item.pay_note || null,
    notes: item.notes || null,
    last_verified_on: item.last_verified_on || null,
    follow_up_on: item.follow_up_on || null,
    state: item.state === "applied" || item.application_removed ? null : item.state,
    dismiss_reason: item.dismiss_reason || null,
  };
  return Object.assign(body, changes || {});
}

function todayIsoDate() {
  const d = new Date();
  const pad = (n) => (n < 10 ? "0" + n : String(n));
  return d.getFullYear() + "-" + pad(d.getMonth() + 1) + "-" + pad(d.getDate());
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

// Shows the card only when the server answers. A switched-off feature answers 404 and stays hidden.
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
  renderOpportunities();
}

function renderOpportunities() {
  const list = document.getElementById("opportunity-list");
  const empty = document.getElementById("opportunity-empty");
  const count = document.getElementById("opportunity-count");
  if (!list) return;
  list.textContent = "";
  const active = allOpportunities.filter((o) => o.state !== "dismissed");
  const dismissed = allOpportunities.filter((o) => o.state === "dismissed");
  if (count) count.textContent = active.length + (active.length === 1 ? " saved link" : " saved links");
  const shown = showDismissedOpportunities ? allOpportunities : active;
  if (empty) empty.hidden = shown.length > 0;
  const toggle = document.getElementById("opportunity-show-dismissed");
  if (toggle) toggle.textContent = showDismissedOpportunities ? "Hide dismissed links" : "Show dismissed links (" + dismissed.length + ")";
  for (const item of shown) list.appendChild(buildOpportunityItem(item));
}

function makeButton(label, onClick, className) {
  const btn = document.createElement("button");
  btn.type = "button";
  btn.textContent = label;
  if (className) btn.className = className;
  btn.addEventListener("click", onClick);
  return btn;
}

function makeLabelled(labelText, control) {
  const label = document.createElement("label");
  label.className = "field";
  const span = document.createElement("span");
  span.textContent = labelText;
  label.appendChild(span);
  label.appendChild(control);
  return label;
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
  if (item.location_text) parts.push(item.location_text);
  meta.textContent = parts.join(" · ");
  li.appendChild(meta);

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

  if (item.last_verified_on) {
    const checked = document.createElement("p");
    checked.className = "hint";
    checked.textContent = "Last checked on the employer’s site: " + item.last_verified_on + ".";
    li.appendChild(checked);
  }

  if (item.approval) {
    const approval = document.createElement("p");
    approval.className = "hint";
    approval.textContent = approvalLabel(item.approval);
    li.appendChild(approval);
  }
  if (item.application_id) {
    const applied = document.createElement("p");
    applied.className = "hint";
    applied.textContent = "An application is recorded for this job. Its approved resume can no longer be changed here.";
    li.appendChild(applied);
  }
  if (item.application_removed) {
    const removed = document.createElement("p");
    removed.className = "hint";
    removed.textContent = "The application recorded for this job was removed from your tracker.";
    li.appendChild(removed);
  }
  if (item.state === "dismissed") {
    const reason = OPPORTUNITY_DISMISS_REASONS.find((r) => r[0] === item.dismiss_reason);
    const dismissed = document.createElement("p");
    dismissed.className = "hint";
    dismissed.textContent = "Dismissed" + (reason ? ": " + reason[1] : "") + ". It is kept, and you can restore it.";
    li.appendChild(dismissed);
  }

  if (item.state !== "dismissed" && item.state !== "applied") {
    li.appendChild(buildFollowUpControls(item));
  }

  const notice = document.createElement("p");
  notice.className = "hint";
  notice.textContent = item.safety_notice;
  li.appendChild(notice);

  const actions = document.createElement("div");
  actions.className = "opportunity-actions";
  if (item.state === "dismissed") {
    actions.appendChild(makeButton("Restore", () => changeOpportunity(item, { state: "saved", dismiss_reason: null }, "Restored to your saved links.")));
  } else {
    actions.appendChild(makeButton("Compare this job", () => compareSavedOpportunity(item.id)));
    if (item.state !== "applied") {
      actions.appendChild(makeButton("Check it is still open", () => changeOpportunity(item, { last_verified_on: todayIsoDate() }, "Checked. The date is saved on this link.")));
      actions.appendChild(makeButton("Report suspicious link", () => changeOpportunity(item, { state: "dismissed", dismiss_reason: "looks_suspicious" },
        "Set aside as suspicious. Check the employer’s site yourself before you share any information."), "btn-secondary"));
      actions.appendChild(buildDismissControls(item));
    }
  }
  actions.appendChild(makeButton("Remove", () => deleteOpportunity(item), "btn-secondary"));
  li.appendChild(actions);
  return li;
}

// Follow-up date: a date to remember, not a reminder. Nothing is sent to anyone.
function buildFollowUpControls(item) {
  const wrap = document.createElement("div");
  wrap.className = "opportunity-followup";
  const input = document.createElement("input");
  input.type = "date";
  input.value = item.follow_up_on || "";
  input.id = "opportunity-followup-" + item.id;
  wrap.appendChild(makeLabelled("Follow-up date (a date to remember; no reminder is sent)", input));
  wrap.appendChild(makeButton("Save follow-up date", () => {
    if (!input.value) { setOpportunityStatus("Choose a date first, or use Clear."); return; }
    changeOpportunity(item, { follow_up_on: input.value }, "Follow-up date saved.");
  }));
  if (item.follow_up_on) {
    wrap.appendChild(makeButton("Clear follow-up date", () => changeOpportunity(item, { follow_up_on: null }, "Follow-up date cleared."), "btn-secondary"));
  }
  return wrap;
}

function buildDismissControls(item) {
  const wrap = document.createElement("div");
  wrap.className = "opportunity-dismiss";
  const select = document.createElement("select");
  select.id = "opportunity-dismiss-reason-" + item.id;
  for (const [value, label] of OPPORTUNITY_DISMISS_REASONS.filter((r) => r[0] !== "looks_suspicious")) {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = label;
    select.appendChild(option);
  }
  wrap.appendChild(makeLabelled("Reason for dismissing", select));
  wrap.appendChild(makeButton("Dismiss this link", () => changeOpportunity(item, { state: "dismissed", dismiss_reason: select.value || "other" }, "Dismissed. You can restore it from the dismissed links.")));
  return wrap;
}

// One PUT of the whole link with the change applied. The result replaces the link in the list.
async function changeOpportunity(item, changes, doneMessage) {
  const res = await authedFetch("/api/career/opportunities/" + item.id, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(buildUpdatePayload(item, changes)),
  });
  if (!res.ok) {
    setOpportunityStatus(await readOpportunityError(res, "That change was not saved."));
    return null;
  }
  const updated = await res.json();
  allOpportunities = allOpportunities.map((o) => (o.id === item.id ? updated : o));
  renderOpportunities();
  setOpportunityStatus(doneMessage);
  return updated;
}

function approvalLabel(approval) {
  if (approval.status === "current") return "Resume approved for this job (this version is unchanged).";
  if (approval.status === "changed_since_approval") return "The resume you approved for this job has changed since. Approve it again to use the new version.";
  if (approval.status === "version_removed") return "The resume you approved for this job was removed.";
  return "";
}

// Opens the job card for this saved link. The member pastes the posting text there.
function compareSavedOpportunity(id) {
  const item = allOpportunities.find((o) => o.id === id);
  if (!item || typeof startJobFromOpportunity !== "function") return;
  startJobFromOpportunity(item);
}

// Records the approval of one résumé version on this saved link. The request carries only the version id: the server
// changes only the approval, so a copy of the link that is out of date cannot overwrite newer details.
async function approveOpportunityResume(id, versionId) {
  const item = allOpportunities.find((o) => o.id === id);
  if (!item || !versionId) return "Choose a saved link and build a resume first.";
  const res = await authedFetch("/api/career/opportunities/" + id + "/approval", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ approved_resume_version_id: versionId }),
  });
  if (!res.ok) return await readOpportunityError(res, "The approval was not saved.");
  const updated = await res.json();
  allOpportunities = allOpportunities.map((o) => (o.id === id ? updated : o));
  renderOpportunities();
  return "Approved. This resume is now the approved version for this saved job.";
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

async function clearDismissedOpportunities() {
  if (typeof window !== "undefined" && typeof window.confirm === "function" && !window.confirm("Remove all dismissed links? This cannot be undone.")) return;
  const res = await authedFetch("/api/career/opportunities?state=dismissed", { method: "DELETE" });
  if (!res.ok) {
    setOpportunityStatus(await readOpportunityError(res, "The dismissed links were not removed."));
    return;
  }
  allOpportunities = allOpportunities.filter((o) => o.state !== "dismissed");
  renderOpportunities();
  setOpportunityStatus("Dismissed links removed.");
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
  const problem = opportunityLinkProblem(payload.job_url);
  if (problem) {
    setOpportunityStatus(problem);
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

document.addEventListener("DOMContentLoaded", () => {
  const form = document.getElementById("opportunity-form");
  if (form) form.addEventListener("submit", submitOpportunityForm);
  const toggle = document.getElementById("opportunities-add-toggle");
  if (toggle) toggle.addEventListener("click", toggleOpportunityForm);
  const cancel = document.getElementById("opportunity-cancel-btn");
  if (cancel) cancel.addEventListener("click", () => { if (form) form.hidden = true; });
  const showDismissed = document.getElementById("opportunity-show-dismissed");
  if (showDismissed) showDismissed.addEventListener("click", () => {
    showDismissedOpportunities = !showDismissedOpportunities;
    renderOpportunities();
  });
  const clearDismissed = document.getElementById("opportunity-clear-dismissed");
  if (clearDismissed) clearDismissed.addEventListener("click", clearDismissedOpportunities);
});
