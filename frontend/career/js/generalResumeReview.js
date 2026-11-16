// Member review of a saved resume (switch ON only): what the saved information supports, the wording to check, what was removed,
// a full preview, and an explicit sign-off. One component, used for the general resume and the job-targeted resume: each use is
// created with createMemberReview(config) and its own element ids. Every server text is written as plain text nodes, never as markup.
// Requires authedFetch(), formatErrorDetail() (login.js), saveResumeBlob() (resumeDownload.js), and resumeTruthModel.js, all loaded first.

function createMemberReview(cfg) {
  const p = cfg.prefix;
  // Each card owns its messages: its own status and error regions (ids carry the prefix). Nothing here writes to the other card.
  const $ = (suffix) => document.getElementById(p + suffix);
  const state = { versionId: null, review: null, preview: null, editingWhere: null, signed: false, removedOpen: false };
  const dl = () => (cfg.downloadId ? document.getElementById(cfg.downloadId) : null);

  function say(text) {
    const el = $("-status");
    if (el) el.textContent = text;
  }

  function fail(text) {
    const el = $("-error");
    if (!el) return;
    el.textContent = text || "";
    el.hidden = !text;
  }

  function url(suffix) {
    return "/api/career/resume-versions/" + encodeURIComponent(state.versionId) + suffix;
  }

  async function json(res) {
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      const error = new Error(formatErrorDetail(err.detail, `Request failed (${res.status})`));
      error.status = res.status;
      throw error;
    }
    return res.json();
  }

  function focusEditor(where) {
    const item = (state.review && state.review.items || []).find((i) => i.where === where);
    const el = item && document.getElementById("truth-edit-" + p + "-" + item.id);
    if (el) el.focus();
  }

  // One statement, text nodes only. The actions shown depend on what the rules allow for it.
  function itemRow(item) {
    const li = document.createElement("li");
    li.className = "truth-item";
    const text = document.createElement("p");
    text.className = "truth-item-text";
    text.id = "truth-text-" + p + "-" + item.id;
    text.textContent = item.text;
    li.appendChild(text);
    const why = document.createElement("p");
    why.className = "hint";
    why.textContent = explanationText(item);
    li.appendChild(why);
    if (item.source) {
      const src = document.createElement("p");
      src.className = "hint";
      src.textContent = "Saved source: " + item.source;
      li.appendChild(src);
    }
    const status = document.createElement("p");
    status.className = "hint";
    status.textContent = describeDecision(item);
    li.appendChild(status);
    li.appendChild(actionsFor(item));
    return li;
  }

  function actionsFor(item) {
    const wrap = document.createElement("div");
    wrap.className = "truth-actions";
    if (state.editingWhere === item.where) {
      wrap.appendChild(editorFor(item));
      return wrap;
    }
    const allowed = allowedActions(item);
    if (allowed.indexOf("keep") !== -1) {
      const label = document.createElement("label");
      label.className = "truth-ack";
      const box = document.createElement("input");
      box.type = "checkbox";
      box.id = "truth-ack-" + p + "-" + item.id;
      const span = document.createElement("span");
      span.textContent = "I have read this and it is true for me";
      label.appendChild(box);
      label.appendChild(span);
      wrap.appendChild(label);
      wrap.appendChild(buttonFor("Keep", item, "keep", box));
    }
    if (allowed.indexOf("edit") !== -1) wrap.appendChild(buttonFor("Edit", item, "edit", null));
    if (allowed.indexOf("remove") !== -1) wrap.appendChild(buttonFor("Remove", item, "remove", null));
    return wrap;
  }

  // A short visible label; the statement it acts on is linked for screen readers.
  function buttonFor(label, item, action, ackBox) {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = action === "remove" ? "btn-secondary" : "";
    btn.textContent = label;
    btn.setAttribute("aria-describedby", "truth-text-" + p + "-" + item.id);
    btn.addEventListener("click", () => {
      if (action === "edit") {
        state.editingWhere = item.where;
        render();
        focusEditor(item.where);
      } else if (action === "keep" && ackBox && !ackBox.checked) {
        fail("Tick “I have read this and it is true for me” before you keep this wording.");
        ackBox.focus();
      } else {
        send(item, action, action === "keep", null);
      }
    });
    return btn;
  }

  function editorFor(item) {
    const box = document.createElement("div");
    box.className = "truth-editor";
    const label = document.createElement("label");
    label.className = "field";
    const span = document.createElement("span");
    span.textContent = "Your wording for this statement";
    const input = document.createElement("textarea");
    input.id = "truth-edit-" + p + "-" + item.id;
    input.rows = 3;
    input.maxLength = EDIT_LIMIT + 50;
    input.value = item.text;
    input.setAttribute("aria-describedby", "truth-text-" + p + "-" + item.id);
    label.appendChild(span);
    label.appendChild(input);
    box.appendChild(label);
    const save = document.createElement("button");
    save.type = "button";
    save.textContent = "Save my wording";
    save.addEventListener("click", () => {
      const problem = editProblem(input.value, item.text, item.where);
      if (problem) {
        fail(problem);
        input.focus();
        return;
      }
      send(item, "edit", false, input.value);
    });
    const cancel = document.createElement("button");
    cancel.type = "button";
    cancel.className = "btn-secondary";
    cancel.textContent = "Cancel";
    cancel.addEventListener("click", () => {
      state.editingWhere = null;
      fail("");
      render();
      // Keyboard focus returns to the statement whose wording was being edited, not to the page body.
      const text = document.getElementById("truth-text-" + p + "-" + item.id);
      const edit = text ? text.closest("li") : null;
      const editButton = edit ? Array.from(edit.querySelectorAll("button")).find((b) => b.textContent === "Edit") : null;
      const target = editButton || text || document.getElementById(p + "-heading");
      if (target) {
        if (target === text) target.setAttribute("tabindex", "-1");
        target.focus();
      }
    });
    box.appendChild(save);
    box.appendChild(cancel);
    return box;
  }

  // The server revalidates every decision. Any decision makes an earlier preview and sign-off out of date.
  async function send(item, action, acknowledge, text) {
    fail("");
    const body = { item_id: item.id, decision: action, acknowledge: Boolean(acknowledge) };
    if (action === "edit") body.text = text;
    try {
      await json(await authedFetch(url("/decisions"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      }));
      state.editingWhere = null;
      await load();
      say(action === "edit" ? "Your wording was checked and saved. Check it again before you sign off." : "Saved.");
      // Keyboard focus stays in the review: on the same statement after Keep or Remove, on the card heading after an edit (the
      // edited statement has a new identity). Focus is never left on the page body.
      const kept = action !== "edit" ? document.getElementById("truth-text-" + p + "-" + item.id) : null;
      const target = kept || document.getElementById(p + "-heading");
      if (target) {
        target.setAttribute("tabindex", "-1");
        target.focus();
      }
    } catch (err) {
      fail(err.message || "That did not save. Please try again.");
    }
  }

  function renderList(el, rows, build) {
    if (!el) return;
    el.textContent = "";
    rows.forEach((row) => el.appendChild(build(row)));
  }

  function render() {
    const review = state.review;
    if (!review) return;
    const sections = truthSections(review);
    renderList($("-supported"), sections.supported, (row) => {
      const li = document.createElement("li");
      li.textContent = row.text;
      const src = document.createElement("p");
      src.className = "hint";
      src.textContent = "Saved source: " + (row.source || "your saved information");
      li.appendChild(src);
      return li;
    });
    renderList($("-derived"), sections.derived, (row) => {
      const li = document.createElement("li");
      li.textContent = row.text;
      const src = document.createElement("p");
      src.className = "hint";
      src.textContent = "Drawn from: " + (row.source || "your saved experience");
      li.appendChild(src);
      return li;
    });
    renderList($("-uncertain"), sections.uncertain, itemRow);
    const empty = $("-uncertain-empty");
    if (empty) empty.hidden = sections.uncertain.length > 0;
    // What a check changed, and why (job-targeted résumés after a recheck). Hidden when there is nothing to show.
    const changed = review.changes || [];
    const changedHead = $("-changed-h");
    if (changedHead) changedHead.hidden = changed.length === 0;
    const changedList = $("-changed");
    if (changedList) changedList.hidden = changed.length === 0;
    renderList(changedList, changed, (row) => {
      const li = document.createElement("li");
      li.textContent = row.text;
      const detail = document.createElement("p");
      detail.className = "hint";
      detail.textContent = (row.kind === "removed" ? "Removed" : row.kind === "classification" ? "Was " + row.before + ", now " + row.after : row.kind) + ". " + (row.why || "");
      li.appendChild(detail);
      return li;
    });
    // F10: the removed statements are kept, collapsed by default, with a visible count and an accessible toggle.
    // Every removed statement is counted here: those taken out before the draft was saved, and those the member chose to remove.
    const memberRemoved = sections.uncertain.filter((i) => i.decision === "remove").map((i) => ({
      text: i.text,
      explanation: "Removed by you. It is excluded from the final document and kept here as history; keep or edit it above to put it back.",
    }));
    const removedRows = sections.removed.concat(memberRemoved);
    const removedCount = removedRows.length;
    const countEl = $("-removed-count");
    if (countEl) countEl.textContent = "(" + removedCount + ")";
    const toggle = $("-removed-toggle");
    const panel = $("-removed-panel");
    if (toggle && panel) {
      toggle.hidden = removedCount === 0;
      if (removedCount === 0) state.removedOpen = false;
      toggle.setAttribute("aria-expanded", state.removedOpen ? "true" : "false");
      toggle.textContent = (state.removedOpen ? "Collapse removed statements" : "Expand removed statements") + " (" + removedCount + ")";
      panel.hidden = !(state.removedOpen && removedCount > 0);
    }
    renderList($("-removed"), removedRows, (row) => {
      const li = document.createElement("li");
      li.textContent = row.text;
      const why = document.createElement("p");
      why.className = "hint";
      why.textContent = row.explanation || "Not supported by your saved information, so it was taken out.";
      li.appendChild(why);
      return li;
    });
    invalidate();
  }

  // A preview and sign-off belong to the content they were made for. Any change to the review hides them.
  function invalidate() {
    state.preview = null;
    state.signed = false;
    const box = $("-preview");
    if (box) box.hidden = true;
    const signed = $("-signed");
    if (signed) signed.hidden = true;
    const download = dl();
    if (download) download.hidden = true;
    updateSignButton();
  }

  function updateSignButton() {
    const btn = $("-signoff-btn");
    if (!btn) return;
    const check = $("-signoff-check");
    const facts = {
      status: state.review ? state.review.status : "",
      previewed: Boolean(state.preview && state.preview.can_sign_off),
      checked: Boolean(check && check.checked),
      editing: state.editingWhere !== null,
    };
    btn.disabled = !canSignOff(facts);
    // F8: when sign-off is unavailable, the reason is written beside the button and linked to it.
    const why = $("-signoff-why");
    const reason = btn.disabled ? signOffBlocker(facts) : "";
    if (why) {
      why.textContent = reason;
      why.hidden = !reason;
    }
    if (reason && why) btn.setAttribute("aria-describedby", why.id); else btn.removeAttribute("aria-describedby");
  }

  async function load() {
    if (!state.versionId) return;
    try {
      state.review = await json(await authedFetch(url("/review")));
      const recheck = $("-recheck-btn");
      if (recheck) recheck.hidden = true;
      render();
      say(state.review.status === "ready"
        ? "Everything is decided. Preview the whole resume to sign it off."
        : "Review the wording below and choose Keep, Edit or Remove for each statement.");
    } catch (err) {
      state.review = null;
      if (err.status === 409 && /not been checked|changed/.test(err.message) && cfg.recheck) {
        const recheck = $("-recheck-btn");
        if (recheck) recheck.hidden = false;
        say("This resume has not been checked yet. Check it against your saved information to review it.");
        return;
      }
      fail(err.message || "Your resume could not be checked. Please try again.");
    }
  }

  async function showPreview() {
    fail("");
    try {
      const preview = await json(await authedFetch(url("/preview")));
      state.preview = preview;
      const text = $("-preview-text");
      text.textContent = "";
      String(preview.rendered_text || "").split("\n").filter((line) => line.trim()).forEach((line) => {
        const para = document.createElement("p");
        para.className = "truth-preview-line";
        para.textContent = line;
        text.appendChild(para);
      });
      $("-preview").hidden = false;
      $("-preview").querySelector("h4").focus();
      updateSignButton();
      if (!preview.can_sign_off) fail("Some statements still need a decision. Decide them above, then preview again.");
    } catch (err) {
      fail(err.message || "The preview could not be prepared. Please try again.");
    }
  }

  async function sign() {
    const preview = state.preview;
    if (!preview || !preview.can_sign_off) return;
    fail("");
    try {
      await json(await authedFetch(url("/signoff"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ finalized_hash: preview.finalized_hash }),
      }));
      state.signed = true;
      $("-signed").hidden = false;
      $("-signed").focus();
      const download = dl();
      if (download) download.hidden = false;
      say("You signed off this resume. You can download it now.");
    } catch (err) {
      fail(err.message || "The sign-off did not save. Preview the resume again.");
      invalidate();
    }
  }

  // The signed download: the server renders the signed content from the stored version.
  async function download(fileName) {
    const res = await authedFetch(url("/document"));
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(formatErrorDetail(err.detail, `Request failed (${res.status})`));
    }
    saveResumeBlob(await res.blob(), fileName);
  }

  // Owner-initiated deterministic check of an older job-targeted resume (saved information only, no AI call).
  async function recheck() {
    fail("");
    try {
      await json(await authedFetch(url("/member-recheck"), { method: "POST" }));
      await load();
      say("Checked against your saved information. Review the wording below.");
    } catch (err) {
      fail(err.message || "This resume could not be checked. Please try again.");
    }
  }

  // Clears this card's own messages, so an earlier result is not left behind when the card is shown again or hidden.
  function clearMessages() {
    say("");
    fail("");
  }

  function start(versionId) {
    state.versionId = versionId;
    state.review = null;
    state.editingWhere = null;
    clearMessages();
    invalidate();
    const section = document.getElementById(p);
    if (section) section.hidden = false;
    load();
  }

  function hide() {
    const section = document.getElementById(p);
    if (section) section.hidden = true;
    state.versionId = null;
    state.review = null;
    state.editingWhere = null;
    clearMessages();
    invalidate();
  }

  (function wire() {
    const removedToggle = $("-removed-toggle");
    if (removedToggle) {
      removedToggle.addEventListener("click", () => {
        state.removedOpen = !state.removedOpen;
        render();
        removedToggle.focus();     // the same control keeps focus after it changes its label
      });
    }
    const previewBtn = $("-preview-btn");
    if (previewBtn) previewBtn.addEventListener("click", showPreview);
    const check = $("-signoff-check");
    if (check) check.addEventListener("change", updateSignButton);
    const signBtn = $("-signoff-btn");
    if (signBtn) signBtn.addEventListener("click", sign);
    const recheckBtn = $("-recheck-btn");
    if (recheckBtn) recheckBtn.addEventListener("click", recheck);
  })();

  return {
    start,
    hide,
    refresh: () => (state.versionId ? load() : undefined),
    download,
    isSigned: () => state.signed,
  };
}

// The general resume card. Its element ids keep the "general-review" prefix.
const generalReview = createMemberReview({ prefix: "general-review", downloadId: "general-resume-download-btn", recheck: false });

function startGeneralReview(versionId) { generalReview.start(versionId); }
function hideGeneralReview() { generalReview.hide(); }
function downloadSignedGeneralResume(fileName) { return generalReview.download(fileName); }
