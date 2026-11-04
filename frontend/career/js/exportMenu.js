// One "Download my information" button opens a small choice: the readable Word copy or the data backup. The two choice buttons keep their ids
// (login.js binds the downloads to them and the delete panel presses them), and focus is only moved when the menu is actually open, so the
// delete-panel path never steals focus.
(function () {
  const toggle = document.getElementById("export-menu-btn");
  const menu = document.getElementById("export-menu");
  if (!toggle || !menu) return;
  function setOpen(open, returnFocus) {
    menu.hidden = !open;
    toggle.setAttribute("aria-expanded", open ? "true" : "false");
    if (open) menu.querySelector("button").focus();
    else if (returnFocus) toggle.focus();
  }
  toggle.addEventListener("click", () => setOpen(menu.hidden, false));
  menu.addEventListener("click", (e) => { if (!menu.hidden && e.target.closest("button")) setOpen(false, true); });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && !menu.hidden) setOpen(false, true); });
  document.addEventListener("click", (e) => { if (!menu.hidden && !e.target.closest(".export-menu-wrap")) setOpen(false, false); });
})();
