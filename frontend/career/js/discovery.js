// Job discovery pilot: "Found for you (pilot)". Hidden unless the server allows it: the routes answer 404 while
// CT_JOB_DISCOVERY_ENABLED is off or the account is not on the allowlist, and the card stays hidden.
// Shows only metadata from approved employer boards, with the reasons for each match. "Review this opportunity" saves a
// link with the existing saved-link route and then opens the existing compare flow. Nothing is applied for the member.
// Relies on authedFetch(), formatErrorDetail() from login.js and readOpportunityError(), compareSavedOpportunity() and
// allOpportunities from opportunities.js. All text is set with textContent (no HTML from the server is inserted).

const DISCOVERY_ARRANGEMENT_LABELS = { remote: "Remote", hybrid: "Hybrid", on_site: "On site" };
const DISCOVERY_EMPLOYMENT_LABELS = { full_time: "Full time", part_time: "Part time", contract: "Contract", temporary: "Temporary", internship: "Internship", other: "Other" };
let discoveryPrefs = null;

function discoveryStatus(text) {
  const el = document.getElementById("discovery-status");
  if (el) el.textContent = text;
}

function discoverySplit(value) {
  return String(value || "").split(",").map((s) => s.trim()).filter(Boolean);
}

function discoveryCheckedValues(name) {
  return Array.from(document.querySelectorAll("input[name='" + name + "']:checked")).map((el) => el.value);
}

async function loadDiscovery() {
  const card = document.getElementById("discovery-card");
  if (!card) return;
  let res;
  try {
    res = await authedFetch("/api/career/job-preferences");
  } catch (err) {
    card.hidden = true;
    return;
  }
  if (!res.ok) {
    card.hidden = true;
    return;
  }
  discoveryPrefs = await res.json();
  card.hidden = false;
  renderDiscoveryPreferences();
  await loadDiscoveryMatches();
}

function renderDiscoveryPreferences() {
  const p = discoveryPrefs;
  if (!p) return;
  const titles = document.getElementById("discovery-titles");
  if (titles) titles.value = (p.target_titles || []).join(", ");
  const locations = document.getElementById("discovery-locations");
  if (locations) locations.value = (p.locations || []).join(", ");
  const remote = document.getElementById("discovery-remote");
  if (remote) remote.checked = !!p.remote_ok;
  const onsite = document.getElementById("discovery-onsite");
  if (onsite) onsite.checked = !!p.onsite_ok;
  const exclude = document.getElementById("discovery-exclude");
  if (exclude) exclude.value = (p.exclude_words || []).join(", ");
  document.querySelectorAll("input[name='discovery-employment']").forEach((el) => {
    el.checked = (p.employment_types || []).includes(el.value);
  });
  const boards = document.getElementById("discovery-boards");
  if (!boards) return;
  boards.textContent = "";
  (p.available_boards || []).forEach((board) => {
    const label = document.createElement("label");
    const input = document.createElement("input");
    input.type = "checkbox";
    input.name = "discovery-board";
    input.value = board.key;
    input.checked = (p.followed_boards || []).includes(board.key);
    label.appendChild(input);
    label.appendChild(document.createTextNode(" " + board.name));
    boards.appendChild(label);
  });
  const limit = document.getElementById("discovery-limit");
  if (limit) limit.textContent = "You can follow up to " + p.follow_limit + " job boards.";
}

async function saveDiscoveryPreferences(event) {
  event.preventDefault();
  const body = {
    target_titles: discoverySplit(document.getElementById("discovery-titles") && document.getElementById("discovery-titles").value),
    locations: discoverySplit(document.getElementById("discovery-locations") && document.getElementById("discovery-locations").value),
    remote_ok: !!(document.getElementById("discovery-remote") && document.getElementById("discovery-remote").checked),
    onsite_ok: !!(document.getElementById("discovery-onsite") && document.getElementById("discovery-onsite").checked),
    employment_types: discoveryCheckedValues("discovery-employment"),
    exclude_words: discoverySplit(document.getElementById("discovery-exclude") && document.getElementById("discovery-exclude").value),
    followed_boards: discoveryCheckedValues("discovery-board"),
  };
  discoveryStatus("Saving your preferences...");
  let res;
  try {
    res = await authedFetch("/api/career/job-preferences", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
  } catch (err) {
    discoveryStatus("Your preferences could not be saved. Check your connection and try again.");
    return;
  }
  if (!res.ok) {
    discoveryStatus(await readOpportunityError(res, "Your preferences could not be saved."));
    return;
  }
  discoveryPrefs = await res.json();
  discoveryStatus("Preferences saved.");
  renderDiscoveryPreferences();
  await loadDiscoveryMatches();
}

async function loadDiscoveryMatches() {
  const list = document.getElementById("discovery-list");
  const message = document.getElementById("discovery-message");
  if (!list) return;
  let res;
  try {
    res = await authedFetch("/api/career/job-matches");
  } catch (err) {
    if (message) message.textContent = "Matches could not be loaded right now.";
    return;
  }
  if (!res.ok) {
    if (message) message.textContent = "Matches could not be loaded right now.";
    return;
  }
  const data = await res.json();
  list.textContent = "";
  if (message) message.textContent = data.message || "";
  (data.matches || []).forEach((match) => list.appendChild(buildDiscoveryItem(match)));
}

function buildDiscoveryItem(match) {
  const li = document.createElement("li");
  li.className = "opportunity-item";
  const title = document.createElement("strong");
  title.textContent = match.title;
  li.appendChild(title);

  const meta = document.createElement("p");
  meta.className = "hint";
  meta.textContent = [
    match.company,
    match.location_text,
    DISCOVERY_ARRANGEMENT_LABELS[match.work_arrangement],
    DISCOVERY_EMPLOYMENT_LABELS[match.employment_type],
    "First seen " + match.first_seen_on,
  ].filter(Boolean).join(" · ");
  li.appendChild(meta);

  const why = document.createElement("p");
  why.className = "hint";
  why.textContent = "Why it matched: " + (match.reasons || []).join("; ");
  li.appendChild(why);

  const actions = document.createElement("div");
  actions.className = "opportunity-actions";
  const review = document.createElement("button");
  review.type = "button";
  review.className = "btn-gold";
  review.textContent = match.already_saved ? "Open saved link" : "Review this opportunity";
  review.addEventListener("click", () => reviewDiscoveryMatch(match, review));
  actions.appendChild(review);

  const link = document.createElement("a");
  link.href = match.job_url;
  link.target = "_blank";
  link.rel = "noopener noreferrer nofollow";
  link.textContent = "Open employer page";
  actions.appendChild(link);
  li.appendChild(actions);
  return li;
}

async function reviewDiscoveryMatch(match, button) {
  button.disabled = true;
  try {
    if (!match.already_saved) {
      let res;
      try {
        res = await authedFetch("/api/career/opportunities", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            title: match.title,
            employer: match.company,
            job_url: match.job_url,
            location_text: match.location_text,
            work_arrangement: match.work_arrangement,
            employment_type: match.employment_type,
          }),
        });
      } catch (err) {
        discoveryStatus("The saved link could not be created. Check your connection and try again.");
        return;
      }
      if (!res.ok && res.status !== 409) {
        discoveryStatus(await readOpportunityError(res, "The saved link could not be created."));
        return;
      }
    }
    if (typeof loadOpportunities === "function") await loadOpportunities();
    const saved = (typeof allOpportunities !== "undefined" ? allOpportunities : []).find((o) => o.job_url === match.job_url);
    if (!saved) {
      discoveryStatus("This link is saved, but could not be opened here. Refresh the page and try again.");
      return;
    }
    await loadDiscoveryMatches();
    compareSavedOpportunity(saved.id);
  } finally {
    button.disabled = false;
  }
}

const discoveryForm = document.getElementById("discovery-prefs-form");
if (discoveryForm) discoveryForm.addEventListener("submit", saveDiscoveryPreferences);
