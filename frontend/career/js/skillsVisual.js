// Skills as a visual: chips grouped under the role each skill belongs to (Groups view), with
// the original row-by-row editor kept as the List view. A skill's note (how it was used) shows
// as the chip's tooltip; editing and deleting stay in List view, like the application Board.
// Relies on allSkills/allExperiences/loadSkills() from login.js. The switch is remembered for
// this tab only (sessionStorage).

// "groups" | "list"
let skillView = "groups";
try {
  if (typeof sessionStorage !== "undefined" && sessionStorage.getItem("ct_skill_view") === "list") skillView = "list";
} catch (err) { /* storage blocked: stay on groups */ }

// Pure helper (unit-tested): [{ key, label, sublabel, skills }] - roles in the profile's order,
// then one "Not tied to one role" group for the rest. Skills inside a group stay in order.
function groupSkillsByRole(skills, experiences) {
  const list = Array.isArray(skills) ? skills : [];
  const roles = Array.isArray(experiences) ? experiences : [];
  const groups = [];
  const byRole = new Map();
  for (const role of roles) {
    const group = { key: "role-" + role.id, label: role.title || "Role", sublabel: role.organization || "", skills: [] };
    byRole.set(role.id, group);
    groups.push(group);
  }
  const general = { key: "general", label: "Not tied to one role", sublabel: "", skills: [] };
  for (const skill of list) {
    const group = skill.experience_id && byRole.has(skill.experience_id) ? byRole.get(skill.experience_id) : general;
    group.skills.push(skill);
  }
  if (general.skills.length) groups.push(general);
  return groups.filter((g) => g.skills.length > 0);
}

function setSkillView(view) {
  skillView = view === "list" ? "list" : "groups";
  try { sessionStorage.setItem("ct_skill_view", skillView); } catch (err) { /* ignore */ }
  if (typeof loadSkills === "function") loadSkills();
}

function syncSkillViewToggle() {
  const toggle = document.getElementById("skill-view-toggle");
  if (!toggle) return;
  toggle.hidden = typeof allSkills === "undefined" || allSkills.length === 0;
  const groupsBtn = document.getElementById("skill-view-groups");
  const listBtn = document.getElementById("skill-view-list");
  if (groupsBtn) groupsBtn.setAttribute("aria-pressed", String(skillView === "groups"));
  if (listBtn) listBtn.setAttribute("aria-pressed", String(skillView === "list"));
}

function renderSkillGroups(container) {
  const groups = groupSkillsByRole(allSkills, typeof allExperiences !== "undefined" ? allExperiences : []);
  const grid = document.createElement("div");
  grid.className = "vis-grid skill-groups";
  groups.forEach((group, i) => {
    const card = document.createElement("section");
    card.className = "skill-group skill-tone-" + (i % 5);
    card.setAttribute("aria-label", group.label);

    const head = document.createElement("div");
    head.className = "skill-group-head";
    const text = document.createElement("div");
    const title = document.createElement("strong");
    title.textContent = group.label;
    text.appendChild(title);
    if (group.sublabel) {
      const sub = document.createElement("span");
      sub.className = "skill-group-sub";
      sub.textContent = group.sublabel;
      text.appendChild(sub);
    }
    head.appendChild(text);
    const count = document.createElement("span");
    count.className = "app-col-count";
    count.textContent = String(group.skills.length);
    head.appendChild(count);
    card.appendChild(head);

    const chips = document.createElement("div");
    chips.className = "skill-chips";
    for (const skill of group.skills) {
      const chip = document.createElement("span");
      chip.className = "skill-chip";
      chip.textContent = skill.name;
      if (skill.source_text) chip.title = skill.source_text;
      chips.appendChild(chip);
    }
    card.appendChild(chips);
    grid.appendChild(card);
  });
  container.appendChild(grid);

  const tip = document.createElement("p");
  tip.className = "hint app-board-tip";
  tip.textContent = "Hover a skill to see how you used it. Switch to List to edit, move or delete a skill.";
  container.appendChild(tip);
}

if (typeof document !== "undefined" && document.getElementById("skill-view-groups")) {
  document.getElementById("skill-view-groups").addEventListener("click", () => setSkillView("groups"));
  document.getElementById("skill-view-list").addEventListener("click", () => setSkillView("list"));
}
