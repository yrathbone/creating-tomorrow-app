// The evidence summary at the keyword step: five counts, status chips and grouped sections, built from what the keyword check already returns.
// Nothing here decides what is true: "backed" appears only where the server already said exact wording, evidence under other words, or a
// met accepted option, and a status is always an icon plus a word (never a colour alone).

// Status chips: an icon, a word and an outline style (the page styles tell them apart without any new colour).
const EVIDENCE_CHIPS = {
  backed: { icon: "✓", word: "Backed", cls: "backed" },
  other: { icon: "≈", word: "Other words", cls: "other" },
  profile: { icon: "＋", word: "In your profile", cls: "profile" },
  question: { icon: "?", word: "One question", cls: "question" },
  none: { icon: "–", word: "Not evidenced", cls: "none" },
};

function evidenceChip(kind) {
  const chip = EVIDENCE_CHIPS[kind];
  const el = document.createElement("span");
  el.className = "evidence-chip evidence-chip-" + chip.cls;
  const icon = document.createElement("span");
  icon.setAttribute("aria-hidden", "true");
  icon.textContent = chip.icon;
  el.appendChild(icon);
  el.appendChild(document.createTextNode(" " + chip.word));
  return el;
}

// Sorts a keyword-check response into the five groups. A term with an alternatives group, or only a different activity behind it
// ("transferable"), is a question; a term with no evidence at all is "not evidenced". `index` is the term's place in data.terms, so the
// question cards keep their saved-choice mapping.
function groupEvidence(data) {
  const terms = (data && data.terms) || [];
  const exact = (data && data.covered_exact) || [];
  const related = (data && data.covered_related) || [];
  const alternatives = (data && data.alternatives_met) || [];
  const questions = [];
  const notEvidenced = [];
  terms.forEach((term, index) => {
    (term.alternatives || term.support === "transferable" ? questions : notEvidenced).push({ term, index });
  });
  return {
    questions,
    notEvidenced,
    tiles: [
      { key: "backed", count: exact.length, label: "already backed by your profile" },
      { key: "other", count: related.length, label: "backed through other words" },
      { key: "alternative", count: alternatives.length, label: "met through another accepted option" },
      { key: "question", count: questions.length, label: "one question each" },
      { key: "none", count: notEvidenced.length, label: "not evidenced yet" },
    ],
  };
}

function renderEvidenceTiles(listEl, tiles) {
  listEl.textContent = "";
  tiles.forEach((tile) => {
    const li = document.createElement("li");
    li.className = "evidence-tile";
    const count = document.createElement("b");
    count.textContent = String(tile.count);
    const label = document.createElement("span");
    label.textContent = tile.label;
    li.appendChild(count);
    li.appendChild(label);
    listEl.appendChild(li);
  });
}

// The same five groups for a finished resume, read from the build report (term_report). Every row lands in exactly one group, so the counts
// always add up; context wording the builder chose not to use is left out, as before. "On your resume" is told apart by how it is backed: the
// profile's own words (literal) or the same activity under other words (related). A different activity (transferable) is never "backed".
function groupReport(report) {
  const rows = (report || []).filter((r) => r.status !== "wording_unused");
  const pick = (test) => rows.filter(test);
  const groups = {
    backed: pick((r) => r.status === "on_resume" && r.support === "literal"),
    other: pick((r) => r.status === "on_resume" && r.support === "related"),
    alternative: pick((r) => r.status === "alternative_met"),
    profile: pick((r) => r.status === "not_placed"),
    question: pick((r) => r.status === "transferable" || (r.status === "on_resume" && r.support === "transferable")),
    none: pick((r) => r.status === "not_in_profile"),
  };
  const label = {
    backed: "on your resume, in your profile’s own words",
    other: "on your resume, backed through other words",
    alternative: "met through another accepted option",
    profile: "in your profile, not on this resume",
    question: "relevant experience, one question",
    none: "not evidenced yet",
  };
  return { total: rows.length, ...groups, tiles: Object.keys(groups).map((key) => ({ key, count: groups[key].length, label: label[key] })) };
}
