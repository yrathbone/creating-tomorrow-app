// "Delete my data and account" (Your Data card). One careful path:
//   1. open the panel (nothing is deleted by opening it); a backup download is offered right there;
//   2. the person must type the word DELETE, which is the only thing that enables the final button;
//   3. our server erases every saved record (POST /api/career/account/delete) in one transaction;
//   4. only then does the browser ask Cognito to remove the sign-in account itself, and the person is
//      signed out and shown a plain confirmation (no dashboard, no data).
// If step 3 fails, nothing was deleted and the panel says so. If step 4 fails, the data is already gone, and
// the confirmation says exactly that and how to finish by email. Relies on authedFetch() from login.js and
// deleteCurrentCognitoUser()/clearCognitoSessionKeys() from auth.js.

const DELETE_ACCOUNT_WORD = "DELETE";
const DELETE_CONTACT_EMAIL = "yovanarathbone@creatingtomorrow.net";

// Pure helpers (unit-tested)
function deleteConfirmationMatches(text) {
  return String(text == null ? "" : text).trim() === DELETE_ACCOUNT_WORD;
}

function deletedMessage(accountRemoved) {
  return accountRemoved
    ? "Your saved data and your sign-in account have been permanently deleted. If you ever want to use the Career Profile again, you're welcome to create a new account."
    : "Your saved data has been permanently deleted and you have been signed out. We couldn't remove your sign-in account automatically. Email " + DELETE_CONTACT_EMAIL + " and we'll remove it for you.";
}

// The server answered "no": it rolls back as one transaction, so nothing was deleted.
function deleteFailureMessage(detail) {
  return (typeof detail === "string" && detail ? detail : "We couldn't delete your data just now.") + " Nothing was deleted. Please try again in a moment.";
}

// The request never got an answer (connection lost): we cannot know whether it finished, so we do not claim either.
function deleteUnknownMessage() {
  return "We couldn't confirm that the deletion finished. Reload this page: if it asks you to sign in again, your data was deleted. If you can still see your dashboard, try again.";
}

function wireDeleteAccount() {
  if (typeof document === "undefined") return;
  const el = (id) => document.getElementById(id);
  const startBtn = el("delete-account-start-btn");
  if (!startBtn) return;
  const panel = el("delete-account-panel");
  const input = el("delete-confirm-input");
  const confirmBtn = el("delete-confirm-btn");
  const cancelBtn = el("delete-cancel-btn");
  const errorEl = el("delete-error");
  let working = false;

  const showError = (text) => { errorEl.textContent = text; errorEl.hidden = !text; };
  const sync = () => { confirmBtn.disabled = working || !deleteConfirmationMatches(input.value); };
  const close = () => {
    panel.hidden = true;
    startBtn.setAttribute("aria-expanded", "false");
    input.value = "";
    showError("");
    sync();
  };

  startBtn.addEventListener("click", () => {
    const open = panel.hidden;
    if (!open) return close();
    panel.hidden = false;
    startBtn.setAttribute("aria-expanded", "true");
    input.focus();
  });
  cancelBtn.addEventListener("click", () => { if (!working) close(); });
  input.addEventListener("input", sync);
  input.addEventListener("keydown", (e) => { if (e.key === "Enter") e.preventDefault(); }); // Enter never deletes

  // The backup button just presses the existing "Download my Career Profile (backup)" button.
  el("delete-backup-btn").addEventListener("click", () => { const b = el("export-profile-btn"); if (b) b.click(); });

  confirmBtn.addEventListener("click", async () => {
    if (working || !deleteConfirmationMatches(input.value)) return;
    working = true;
    cancelBtn.disabled = true;
    confirmBtn.textContent = "Deleting...";
    sync();
    showError("");
    const stop = (message) => {
      working = false;
      cancelBtn.disabled = false;
      confirmBtn.textContent = "Permanently delete everything";
      showError(message);
      sync();
    };
    let res;
    try {
      res = await authedFetch("/api/career/account/delete", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ confirm: DELETE_ACCOUNT_WORD }),
      });
    } catch (err) {
      return stop(deleteUnknownMessage());
    }
    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      return stop(deleteFailureMessage(body && body.detail));
    }

    // Our side is erased. Now remove the sign-in account itself.
    let accountRemoved = true;
    try { await deleteCurrentCognitoUser(); } catch (err) { accountRemoved = false; }
    try { clearCognitoSessionKeys(); } catch (err) { /* nothing left to clear */ }
    if (typeof currentAccessToken !== "undefined") currentAccessToken = null;

    el("step-profile").hidden = true;
    const signout = el("nav-signout");
    if (signout) signout.hidden = true;
    el("deleted-message").textContent = deletedMessage(accountRemoved);
    el("step-deleted").hidden = false;
    window.scrollTo(0, 0);
  });
}

wireDeleteAccount();
