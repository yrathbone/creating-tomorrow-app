// Member resume review: the pure rules behind the review screen (no DOM access). Loaded before generalResumeReview.js in the browser,
// and loaded by the node regression tests (backend/tests/frontend/resumeTruthModel.test.js). The server is the authority: every
// decision, edit and sign-off is checked again there. These rules only decide what the screen offers and explains.

// Supported rows that repeat the same wording (for example a skill that also appears as a headline phrase) are shown once. Every
// saved source is kept: the row lists each one, so no evidence is lost (F2).
function dedupeSupported(rows) {
  const byText = new Map();
  (rows || []).forEach((row) => {
    const key = String((row && row.text) || "").replace(/\s+/g, " ").trim().toLowerCase();
    if (!key) { byText.set(Symbol("row"), row); return; }
    const source = String((row && row.source) || "").trim();
    if (!byText.has(key)) { byText.set(key, { ...row, sources: source ? [source] : [] }); return; }
    const kept = byText.get(key);
    if (source && kept.sources.indexOf(source) === -1) kept.sources.push(source);
  });
  return Array.from(byText.values()).map((row) => {
    const sources = row.sources || [];
    const out = { ...row, source: sources.length ? sources.join("; ") : row.source };
    delete out.sources;
    return out;
  });
}

// The sections of a review, from the review endpoint's answer.
function truthSections(review) {
  const items = (review && review.items) || [];
  return {
    supported: dedupeSupported((review && review.supported) || []),   // SUPPORTED: exact match to saved information
    derived: (review && review.derived) || [],              // DERIVED: skills drawn from saved experience, with the evidence
    uncertain: items.filter((i) => i.classification === "UNCERTAIN"),     // needs the member's decision
    unsupported: items.filter((i) => i.classification === "UNSUPPORTED"),
    removed: (review && review.removed) || [],              // taken out of the draft before it was saved
  };
}

// Only wording that needs a decision can be kept, edited or removed. Unsupported wording cannot be confirmed by anyone.
function allowedActions(item) {
  return item && item.classification === "UNCERTAIN" ? ["keep", "edit", "remove"] : [];
}

function describeDecision(item) {
  if (!item || !item.decision) return "Not decided yet";
  if (item.decision === "keep") return "You kept this wording";
  if (item.decision === "remove") return "Removed by you: excluded from the final document. It stays here as history.";
  return "Decided";
}

// The same limits the server applies, so the screen can explain a problem before sending it.
const EDIT_LIMIT = 300;
function editProblem(text, original, where) {
  const wording = String(text || "").replace(/\s+/g, " ").trim();
  if (!wording) return "Write the statement you want, or choose Remove.";
  if (wording.length > EDIT_LIMIT) return "Keep the statement under 300 characters.";
  if (/^headline/.test(String(where || "")) && wording.indexOf("|") !== -1) return "Write one headline phrase without the '|' character.";
  if (wording === String(original || "").replace(/\s+/g, " ").trim()) return "The wording has not changed. Choose Keep to confirm it, or change the wording.";
  return "";
}

// Sign-off is offered only for a preview of the complete resume, after every statement is decided and no edit is pending.
function canSignOff(state) {
  return Boolean(state && state.status === "ready" && state.previewed && state.checked && !state.editing);
}

// Why sign-off is not available yet, in plain words, or "" when it is available. Shown beside the disabled button (F8).
function signOffBlocker(state) {
  if (!state || state.status !== "ready") return "Decide every statement first: keep, edit or remove each one under Wording to check.";
  if (state.editing) return "Save or cancel your wording first, then preview the whole resume again.";
  if (!state.previewed) return "Preview the whole resume first. Sign-off is available after you preview it.";
  if (!state.checked) return "Tick the box under the preview to confirm the whole resume is true for you.";
  return "";
}

// Plain, readable line for a review entry's explanation (the server's text, shown as given).
function explanationText(item) {
  return String((item && item.explanation) || "").trim();
}

if (typeof module !== "undefined" && module.exports) {
  module.exports = { truthSections, dedupeSupported, allowedActions, describeDecision, editProblem, canSignOff, signOffBlocker, explanationText, EDIT_LIMIT };
}
