// Resume-header basics: the saved name and contact line from the Career Profile.
// Phase 2B prefilled the General Resume and tailored-resume inputs from them;
// Phase 2C adds the small "Your resume header" form in the My Career card that
// saves them. Relies on authedFetch() from login.js.

let profileBasics = { display_name: null, contact_line: null };

async function loadProfileBasics() {
  try {
    const res = await authedFetch("/api/career/profile");
    if (!res.ok) return; // e.g. the database upgrade is not applied yet: forms simply stay empty
    const data = await res.json();
    profileBasics = { display_name: data.display_name || null, contact_line: data.contact_line || null };
  } catch (err) {
    // Prefill is a convenience: never block or break the dashboard over it.
  }
  renderProfileBasicsForm();
}

// Fills an input only when it is empty, so anything the person already typed is kept.
function prefillResumeHeader(nameInput, contactInput) {
  if (nameInput && !nameInput.value.trim() && profileBasics.display_name) nameInput.value = profileBasics.display_name;
  if (contactInput && !contactInput.value.trim() && profileBasics.contact_line) contactInput.value = profileBasics.contact_line;
}

// Shows the saved values in the My Career card's own form.
function renderProfileBasicsForm() {
  if (typeof document === "undefined") return;
  const name = document.getElementById("profile-display-name");
  const contact = document.getElementById("profile-contact-line");
  if (name) name.value = profileBasics.display_name || "";
  if (contact) contact.value = profileBasics.contact_line || "";
}

// Saves through PUT /api/career/profile (owner comes from the sign-in, never from this request).
// Resolves {ok: true} or {ok: false, message}.
async function saveProfileBasics(displayName, contactLine) {
  const display_name = (displayName || "").trim() || null;
  const contact_line = (contactLine || "").trim() || null;
  try {
    const res = await authedFetch("/api/career/profile", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ display_name, contact_line }),
    });
    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      return { ok: false, message: typeof body.detail === "string" ? body.detail : "Couldn't save that right now." };
    }
    const data = await res.json();
    profileBasics = { display_name: data.display_name || null, contact_line: data.contact_line || null };
    return { ok: true };
  } catch (err) {
    return { ok: false, message: (err && err.message) || "Couldn't save that right now." };
  }
}

if (typeof document !== "undefined" && document.getElementById("profile-basics-form")) {
  document.getElementById("profile-basics-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const btn = document.getElementById("profile-basics-save-btn");
    const msg = document.getElementById("profile-basics-msg");
    btn.disabled = true;
    msg.hidden = true;
    const result = await saveProfileBasics(
      document.getElementById("profile-display-name").value,
      document.getElementById("profile-contact-line").value
    );
    btn.disabled = false;
    msg.textContent = result.ok ? "Saved." : result.message;
    msg.className = result.ok ? "hint mc-saved" : "hint error";
    msg.hidden = false;
    if (result.ok) {
      renderProfileBasicsForm();
      if (typeof setProfileEditorOpen === "function") setProfileEditorOpen(false); // the strip above shows the saved values
    }
  });
}
