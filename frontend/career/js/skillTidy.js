// "Shorten long skill names": saved skills should have short keyword names, with
// the descriptive sentence kept as reference. The server only PROPOSES a
// keyword for each long name (POST /skills-tidy-suggest, read-only); every
// change is reviewed here and saved through the normal PUT /skills/{id}.
// Relies on authedFetch()/formatErrorDetail()/loadSkills() from login.js.

// Quick add: one short keyword, saved straight to the skill bank.
document.getElementById("skill-quick-add-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const input = document.getElementById("skill-quick-add-input");
  const msg = document.getElementById("skill-quick-add-msg");
  const name = input.value.trim();
  if (!name) return;
  msg.hidden = false;
  if (name.split(/\s+/).length > 4) {
    msg.textContent = "Keep a skill to a short keyword (up to 4 words). Put longer detail in the skill's edit form.";
    return;
  }
  const res = await authedFetch("/api/career/skills", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name, source_text: null, experience_id: null }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    msg.textContent = formatErrorDetail(err.detail, "Couldn't save that skill.");
    return;
  }
  input.value = "";
  msg.textContent = '"' + name + '" added. Use Edit on it to attach a role or a sentence.';
  if (typeof loadSkills === "function") await loadSkills();
});

let tidySuggestions = [];

const skillTidyPanel = document.getElementById("skill-tidy-panel");

document.getElementById("skill-tidy-btn").addEventListener("click", async () => {
  const btn = document.getElementById("skill-tidy-btn");
  const errorEl = document.getElementById("skill-tidy-error");
  errorEl.hidden = true;
  btn.disabled = true;
  const original = btn.textContent;
  btn.textContent = "Reading your skills...";
  try {
    const res = await authedFetch("/api/career/skills-tidy-suggest", { method: "POST" });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(formatErrorDetail(err.detail, `Request failed (${res.status})`));
    }
    const data = await res.json();
    tidySuggestions = data.suggestions || [];
    renderTidySuggestions();
    skillTidyPanel.hidden = false;
  } catch (err) {
    skillTidyPanel.hidden = false;
    document.getElementById("skill-tidy-list").textContent = "";
    errorEl.textContent = err.message || "Something went wrong. Please try again.";
    errorEl.hidden = false;
  } finally {
    btn.disabled = false;
    btn.textContent = original;
  }
});

function renderTidySuggestions() {
  const list = document.getElementById("skill-tidy-list");
  list.textContent = "";
  document.getElementById("skill-tidy-error").hidden = true;
  document.getElementById("skill-tidy-apply-btn").hidden = tidySuggestions.length === 0;
  document.getElementById("skill-tidy-intro").textContent = tidySuggestions.length
    ? "These skill names are longer than a keyword. Edit any suggestion, untick the ones you want to leave alone, then save. The old name is kept as the reference sentence when a skill has none."
    : "All your skill names are already short keywords.";

  tidySuggestions.forEach((s, i) => {
    const card = document.createElement("div");
    card.className = "question-card";
    card.dataset.index = String(i);

    const label = document.createElement("label");
    const check = document.createElement("input");
    check.type = "checkbox";
    check.className = "tidy-check";
    check.checked = true;
    label.appendChild(check);
    label.appendChild(document.createTextNode(" Rename"));
    card.appendChild(label);

    const old = document.createElement("p");
    old.className = "hint";
    old.style.fontWeight = "400";
    old.textContent = "Now: " + s.name;
    card.appendChild(old);

    const input = document.createElement("input");
    input.type = "text";
    input.className = "tidy-name";
    input.value = s.keyword;
    card.appendChild(input);

    if (s.source_text) {
      const ref = document.createElement("p");
      ref.className = "hint";
      ref.style.fontWeight = "400";
      ref.textContent = "Reference kept: " + s.source_text;
      card.appendChild(ref);
    }
    list.appendChild(card);
  });
}

document.getElementById("skill-tidy-cancel-btn").addEventListener("click", () => {
  skillTidyPanel.hidden = true;
});

document.getElementById("skill-tidy-apply-btn").addEventListener("click", async () => {
  const errorEl = document.getElementById("skill-tidy-error");
  errorEl.hidden = true;
  const btn = document.getElementById("skill-tidy-apply-btn");
  btn.disabled = true;

  let saved = 0;
  try {
    for (const card of document.querySelectorAll("#skill-tidy-list .question-card")) {
      if (!card.querySelector(".tidy-check").checked) continue;
      const s = tidySuggestions[Number(card.dataset.index)];
      const name = card.querySelector(".tidy-name").value.trim();
      if (!name) continue;
      const res = await authedFetch("/api/career/skills/" + s.id, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        // PUT replaces all three fields, so send them all. The old name becomes the
        // reference text when the skill had no sentence of its own.
        body: JSON.stringify({ name, source_text: s.source_text || s.name, experience_id: s.experience_id }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(formatErrorDetail(err.detail, `Couldn't rename "${s.name}" (${res.status})`));
      }
      saved += 1;
      card.querySelector(".tidy-check").checked = false;
    }
  } catch (err) {
    errorEl.textContent = err.message + (saved ? " (" + saved + " already saved and unticked.)" : "");
    errorEl.hidden = false;
    btn.disabled = false;
    if (saved && typeof loadSkills === "function") await loadSkills();
    return;
  }

  btn.disabled = false;
  if (typeof loadSkills === "function") await loadSkills();
  document.getElementById("skill-tidy-list").textContent = "";
  document.getElementById("skill-tidy-apply-btn").hidden = true;
  document.getElementById("skill-tidy-intro").textContent = saved + (saved === 1 ? " skill renamed." : " skills renamed.");
});
