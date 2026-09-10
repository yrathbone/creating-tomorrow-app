// Guide V1: a deterministic navigation assistant, not a chatbot. No LLM, no
// free text, no backend calls - just a flat lookup from a situation to a
// recommended tool. Kept as its own small data table (GUIDE_OPTIONS) so a
// future version could swap this lookup for a real routing call without
// touching how the modal renders or behaves.
const GUIDE_OPTIONS = [
  {
    id: "create",
    label: "I need to create a resume",
    toolName: "Beginning",
    toolHref: "scratch.html",
    explanation: "Since you don't have a resume yet, Beginning walks you through building one from scratch, step by step, using your real experience.",
  },
  {
    id: "improve",
    label: "I want to improve the resume I already have",
    toolName: "Refine",
    toolHref: "tool.html?mode=refine",
    explanation: "Since you already have a resume and want it to read more polished and professional, Refine strengthens your language and formatting using only what's already true.",
  },
  {
    id: "hidden-experience",
    label: "My resume doesn't show everything I can do",
    toolName: "Elevate",
    toolHref: "elevate.html",
    explanation: "Since you already have a resume but feel it doesn't fully represent your experience, Elevate can help uncover what may be missing.",
  },
  {
    id: "specific-job",
    label: "I found a job I want",
    toolName: "Right Fit",
    toolHref: "tool.html?mode=analyze",
    explanation: "Since you have a specific job in mind, Right Fit compares your resume to that posting and gives you an honest sense of how well you match.",
  },
];

const guideModal = document.getElementById("guide-modal");
const guideStepOptions = document.getElementById("guide-step-options");
const guideStepRecommendation = document.getElementById("guide-step-recommendation");
const guideOptionsList = document.getElementById("guide-options-list");
const guideRecommendationHeading = document.getElementById("guide-recommendation-heading");
const guideRecommendationText = document.getElementById("guide-recommendation-text");
const guideStartBtn = document.getElementById("guide-start-btn");

function renderGuideOptions() {
  guideOptionsList.innerHTML = "";
  GUIDE_OPTIONS.forEach((option) => {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "mode-btn guide-option-btn";
    btn.textContent = option.label;
    btn.addEventListener("click", () => showGuideRecommendation(option));
    guideOptionsList.appendChild(btn);
  });
}

function showGuideRecommendation(option) {
  guideRecommendationHeading.textContent = `Here's where I'd start: ${option.toolName}.`;
  guideRecommendationText.textContent = option.explanation;
  guideStartBtn.textContent = `Start ${option.toolName}`;
  guideStartBtn.href = option.toolHref;

  guideStepOptions.hidden = true;
  guideStepRecommendation.hidden = false;
}

function openGuide() {
  renderGuideOptions();
  guideStepOptions.hidden = false;
  guideStepRecommendation.hidden = true;
  guideModal.hidden = false;
}

function closeGuide() {
  guideModal.hidden = true;
}

document.getElementById("guide-open-btn").addEventListener("click", openGuide);
document.getElementById("guide-close-btn").addEventListener("click", closeGuide);
document.getElementById("guide-back-btn").addEventListener("click", () => {
  guideStepRecommendation.hidden = true;
  guideStepOptions.hidden = false;
});

guideModal.addEventListener("click", (e) => {
  if (e.target === guideModal) closeGuide();
});

document.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && !guideModal.hidden) closeGuide();
});
