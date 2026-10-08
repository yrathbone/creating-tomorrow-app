// Resume-header basics (Phase 2B): the saved name and contact line from the
// Career Profile, used only to PREFILL the existing name/contact inputs of the
// General Resume and job-tailored resume forms. Nothing here saves anything and
// the forms are otherwise unchanged. Relies on authedFetch() from login.js.

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
}

// Fills an input only when it is empty, so anything the person already typed is kept.
function prefillResumeHeader(nameInput, contactInput) {
  if (nameInput && !nameInput.value.trim() && profileBasics.display_name) nameInput.value = profileBasics.display_name;
  if (contactInput && !contactInput.value.trim() && profileBasics.contact_line) contactInput.value = profileBasics.contact_line;
}
