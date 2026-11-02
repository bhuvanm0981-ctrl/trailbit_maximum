import { eachForIssue } from "./dom.js";
import { markCurrentStep } from "./plan.js";
import { $, PROGRESS_PREFIX, state } from "./state.js";
import { plural } from "./ui.js";

/* ====================================================================
   Progress store: Map(issueId -> Set(stepNumber)), persisted per issue in localStorage
   ==================================================================== */
export function loadProgress(issueId) {
  try {
    const parsed = JSON.parse(localStorage.getItem(PROGRESS_PREFIX + issueId) || "[]");
    return new Set(Array.isArray(parsed) ? parsed.filter(Number.isInteger) : []);
  } catch {
    return new Set();
  }
}

export function saveProgress(issueId) {
  try {
    const steps = [...progressFor(issueId)].sort((a, b) => a - b);
    localStorage.setItem(PROGRESS_PREFIX + issueId, JSON.stringify(steps));
  } catch { /* storage unavailable: progress lasts for this page view only */ }
}

export function progressFor(issueId) {
  if (!state.progress.has(issueId)) state.progress.set(issueId, loadProgress(issueId));
  return state.progress.get(issueId);
}

/** Read every saved issue's progress, so the bar covers issues started on earlier visits too. */
export function loadAllProgress() {
  try {
    for (let i = 0; i < localStorage.length; i++) {
      const key = localStorage.key(i);
      if (key && key.startsWith(PROGRESS_PREFIX)) progressFor(key.slice(PROGRESS_PREFIX.length));
    }
  } catch { /* storage unavailable */ }
}

export const isDone = (issueId, stepNumber) => progressFor(issueId).has(stepNumber);

/** Steps in an issue's checklist: its own if we have fetched it, otherwise the standard length. */
export function totalSteps(issueId) {
  const issue = state.byId.get(issueId);
  const own = issue && Array.isArray(issue.actionable_checklist) ? issue.actionable_checklist.length : 0;
  return own || state.checklistLength;
}

/** Completed steps for an issue (or an issue id). Saved numbers outside the checklist are ignored. */
export function countDone(issueOrId) {
  const id = typeof issueOrId === "string" ? issueOrId : issueOrId.id;
  const total = totalSteps(id);
  let done = 0;
  for (const step of progressFor(id)) if (step >= 1 && step <= total) done++;
  return done;
}

export const startedIssueIds = () => [...state.progress.keys()].filter((id) => countDone(id) > 0);

export function registerIssue(issue) {
  if (!issue || !issue.id) return;
  const known = state.byId.get(issue.id);
  // A list summary has no checklist; never let it replace a fuller record from the live check.
  if (known && Array.isArray(known.actionable_checklist) && !Array.isArray(issue.actionable_checklist)) return;
  state.byId.set(issue.id, issue);
}

export function toggleStep(issueId, stepNumber, checked) {
  const set = progressFor(issueId);
  if (checked) set.add(stepNumber);
  else set.delete(stepNumber);
  saveProgress(issueId);
  syncIssue(issueId);
}

/** Repaint every place that shows this issue's progress. No re-render, so focus and scroll stay put. */
export function syncIssue(issueId) {
  const total = totalSteps(issueId);
  const done = countDone(issueId);
  const percent = total ? Math.round((done / total) * 100) : 0;

  eachForIssue("input[data-step]", issueId, (input) => {
    const finished = isDone(issueId, Number(input.dataset.step));
    if (input.checked !== finished) input.checked = finished;
    paintRow(input.closest(".step-row"), finished);
  });
  eachForIssue("[data-count]", issueId, (node) => { node.textContent = `${done} of ${total} steps`; });
  eachForIssue("[data-fill]", issueId, (node) => { node.style.width = `${percent}%`; });

  renderGlobalProgress();
  markCurrentStep();
}

export function paintRow(row, finished) {
  if (!row) return;
  row.classList.toggle("is-done", finished);
  const text = row.querySelector(".step-text");
  // Inline decoration as well as the stylesheet rule, so the strike-through always follows the checkbox.
  if (text) text.style.textDecoration = finished ? "line-through" : "none";
}

/** The bar covers every issue you have started (ticked at least one step on), not the whole list on screen. */
export function renderGlobalProgress() {
  const started = startedIssueIds();
  const total = started.reduce((sum, id) => sum + totalSteps(id), 0);
  const done = started.reduce((sum, id) => sum + countDone(id), 0);
  const finished = started.filter((id) => countDone(id) >= totalSteps(id)).length;
  const percent = total ? Math.round((done / total) * 100) : 0;

  $("progress-label").textContent = `Onboarding Progress: ${percent}% Complete`;
  $("progress-fill").style.width = `${percent}%`;
  const bar = $("progress-bar");
  bar.setAttribute("aria-valuenow", String(percent));
  // A bare "42" is meaningless to a screen reader; valuetext says what the number measures.
  bar.setAttribute("aria-valuetext", total ? `${percent}% complete, ${done} of ${total} steps done on ${plural(started.length, "issue")}` : "No issue started yet");
  bar.classList.toggle("is-complete", total > 0 && done === total);
  $("progress-detail").textContent = total
    ? `${done} of ${total} steps done on the ${plural(started.length, "issue")} you started, ${finished} finished`
    : "You have not started an issue yet. Press Inspect issue on a card to begin.";
}
