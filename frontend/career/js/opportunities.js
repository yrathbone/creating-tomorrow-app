// My Opportunities (C-52 MVP-0), smallest member flow: a dashboard tile, add a job link by hand,
// view saved links, remove one. The server never fetches a link. Nothing here scrapes, alerts,
// emails or applies for a job. Relies on authedFetch() and formatErrorDetail() from login.js.
// Feature switch: the server answers 404 while CT_OPPORTUNITIES_ENABLED is off, and the card
// stays hidden. Every piece of saved text is written with textContent, never as markup.

let allOpportunities = [];

const OPPORTUNITY_STATE_LABELS = { saved: "Saved", dismissed: "Dismissed", applied: "Applied" };
const OPPORTUNITY_PERIOD_LABELS = { hourly: "per hour", annual: "per year" };

// Returns the URL only when it is an https link with no username or password; otherwise null.
function safeHttpsHref(raw) {
  try {
    const u = new URL(String(raw || ""));
    if (u.protocol !== "https:" || u.username || u.password) return null;
    return u.href;
  } catch (err) {
    return null;
  }
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
  if (!list) return;
  list.textContent = "";
  if (empty) empty.hidden = allOpportunities.length > 0;
  for (const item of allOpportunities) list.appendChild(buildOpportunityItem(item));
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

  const notice = document.createElement("p");
  notice.className = "hint";
  notice.textContent = item.safety_notice;
  li.appendChild(notice);

  const actions = document.createElement("div");
  actions.className = "opportunity-actions";
  actions.appendChild(makeButton("Remove", () => deleteOpportunity(item), "btn-secondary"));
  li.appendChild(actions);
  return li;
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

document.addEventListener("DOMContentLoaded", () => {
  const form = document.getElementById("opportunity-form");
  if (form) form.addEventListener("submit", submitOpportunityForm);
  const toggle = document.getElementById("opportunities-add-toggle");
  if (toggle) toggle.addEventListener("click", toggleOpportunityForm);
  const cancel = document.getElementById("opportunity-cancel-btn");
  if (cancel) cancel.addEventListener("click", () => { if (form) form.hidden = true; });
});
