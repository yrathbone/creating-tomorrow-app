// Shared processing/waiting-state helper, used by tool.html (app.js),
// scratch.html (scratch.js), and elevate.html (elevate.js). Purely
// presentational - no fetch calls, no resume data, no tool logic. This is a
// deliberate exception to this codebase's usual "no shared JS between
// pages" convention: the alternative was six independent copies of the same
// timer/animation logic that would drift out of sync over time, and the
// goal here is one consistent processing experience across every tool.
//
// Time-based only, on purpose - there is no backend polling or progress
// signal for any of these requests (one fetch, one response), so the
// rotating messages are reassurance/orientation, not real completion
// milestones. Never show a fake percentage.

const PROCESSING_LONG_WAIT_MS = 60000;
const PROCESSING_ROTATE_MS = 6000;
const PROCESSING_LONG_WAIT_TEXT = "Still working — some resumes take a little longer to analyze. Please keep this page open.";

function startProcessingState(container, messages) {
  const statusEl = container.querySelector(".processing-status");
  const waitCopyEl = container.querySelector(".processing-wait-copy");
  if (!statusEl || !messages || !messages.length) return;

  const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  let idx = 0;
  statusEl.textContent = messages[0];

  const messageTimer = setInterval(() => {
    if (idx >= messages.length - 1) return; // hold on the last message rather than looping
    idx += 1;
    if (reduceMotion) {
      statusEl.textContent = messages[idx];
    } else {
      statusEl.classList.add("processing-status-fade");
      setTimeout(() => {
        statusEl.textContent = messages[idx];
        statusEl.classList.remove("processing-status-fade");
      }, 200);
    }
  }, PROCESSING_ROTATE_MS);

  const longWaitTimer = setTimeout(() => {
    if (waitCopyEl) waitCopyEl.textContent = PROCESSING_LONG_WAIT_TEXT;
  }, PROCESSING_LONG_WAIT_MS);

  container._processingTimers = { messageTimer, longWaitTimer };
}

function stopProcessingState(container) {
  const timers = container._processingTimers;
  if (timers) {
    clearInterval(timers.messageTimer);
    clearTimeout(timers.longWaitTimer);
    container._processingTimers = null;
  }
}
