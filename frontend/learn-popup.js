// Homepage "Learning" button: opens a popup listing every article, so a visitor can pick one.
// Same look and behaviour as the Guide Me popup (guide.js). The articles come from learn-data.js (ARTICLES),
// so a new article shows up here with no change to this file. The button is also a plain link to learn.html,
// so it still works when scripts do not run.
const learnModal = document.getElementById("learn-modal");
const learnOptionsList = document.getElementById("learn-options-list");
let learnOpener = null;

function renderLearnOptions() {
  learnOptionsList.innerHTML = "";
  ARTICLES.forEach((article) => {
    const link = document.createElement("a");
    link.className = "mode-btn guide-option-btn learn-option";
    link.href = `article.html?slug=${encodeURIComponent(article.slug)}`;
    const category = document.createElement("span");
    category.className = "learn-option-category";
    category.textContent = article.category;
    const title = document.createElement("span");
    title.className = "learn-option-title";
    title.textContent = article.title;
    link.append(category, title);
    learnOptionsList.appendChild(link);
  });
}

function openLearn(opener) {
  learnOpener = opener || null;
  renderLearnOptions();
  learnModal.hidden = false;
  const first = learnOptionsList.querySelector("a");
  (first || document.getElementById("learn-close-btn")).focus();
}

function closeLearn() {
  learnModal.hidden = true;
  if (learnOpener) learnOpener.focus();
}

document.querySelectorAll("[data-learn-open]").forEach((el) => {
  el.addEventListener("click", (e) => {
    e.preventDefault();
    openLearn(el);
  });
});

document.getElementById("learn-close-btn").addEventListener("click", closeLearn);
learnModal.addEventListener("click", (e) => {
  if (e.target === learnModal) closeLearn();
});
document.addEventListener("keydown", (e) => {
  if (learnModal.hidden) return;
  if (e.key === "Escape") closeLearn();
  if (e.key === "Tab") {
    // keep keyboard focus inside the popup while it is open
    const items = [...learnModal.querySelectorAll("a[href], button")];
    const first = items[0];
    const last = items[items.length - 1];
    if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
    else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
  }
});
