// One card for every dashboard list: a colour-topped white card with an icon tile, a small
// type label, an optional badge, a title, a few lines of detail and a footer (date or note on the
// left, buttons on the right). Job & Skill Scans, Resumes Built, Applications, Roles, Education,
// Certifications, Skills and Languages all build their cards here so they look the same.
// Loaded before login.js and the other dashboard scripts.

function shortDate(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  return isNaN(d) ? "" : d.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
}

function visualButton(label, className, onClick) {
  const b = document.createElement("button");
  b.type = "button";
  b.className = className;
  b.textContent = label;
  b.addEventListener("click", onClick);
  return b;
}

// opts: { kind, tone, typeLabel, badge, badgeTitle, title, lines[], summary, extra, footerText, actions[] }
// kind picks the icon (role, education, certification, skill, language, resume, application,
// job_comparison, skill_scan); tone picks the colour (strong, good, fair, low, skill, pink, neutral).
// Pass an existing element as `into` to rebuild a card in place (the editable cards do this).
function buildVisualCard(opts, into) {
  const card = into || document.createElement("article");
  card.className = "vcard vtone-" + (opts.tone || "neutral") + " vkind-" + opts.kind;
  card.textContent = "";

  const top = document.createElement("div");
  top.className = "vcard-top";
  const icon = document.createElement("span");
  icon.className = "vcard-icon";
  icon.setAttribute("aria-hidden", "true");
  top.appendChild(icon);
  const type = document.createElement("span");
  type.className = "vcard-type";
  type.textContent = opts.typeLabel || "";
  top.appendChild(type);
  if (opts.badge) {
    const badge = document.createElement("span");
    badge.className = "vcard-badge";
    badge.textContent = opts.badge;
    if (opts.badgeTitle) badge.title = opts.badgeTitle;
    top.appendChild(badge);
  }
  card.appendChild(top);

  const title = document.createElement("strong");
  title.className = "vcard-title";
  title.textContent = opts.title || "";
  card.appendChild(title);

  for (const text of opts.lines || []) {
    if (!text) continue;
    const line = document.createElement("span");
    line.className = "vcard-line";
    line.textContent = text;
    card.appendChild(line);
  }

  if (opts.summary) {
    const summary = document.createElement("p");
    summary.className = "vcard-summary";
    summary.textContent = opts.summary;
    card.appendChild(summary);
  }

  if (opts.extra) {
    for (const el of [].concat(opts.extra)) card.appendChild(el);
  }

  const foot = document.createElement("div");
  foot.className = "vcard-foot";
  const date = document.createElement("span");
  date.className = "vcard-date";
  date.textContent = opts.footerText || "";
  foot.appendChild(date);
  const actions = document.createElement("span");
  actions.className = "vcard-actions";
  for (const a of opts.actions || []) actions.appendChild(a);
  foot.appendChild(actions);
  card.appendChild(foot);

  return card;
}
