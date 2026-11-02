import { api, postJson } from "./api.js";
import { h } from "./dom.js";
import { goLayer } from "./layers.js";
import { renderPlan } from "./plan.js";
import { renderApproach, renderCheck, renderGuide, renderUnderstand } from "./problem.js";
import { registerIssue } from "./progress.js";
import { $, state } from "./state.js";

export let selectionToken = 0;

/* ====================================================================
   Selection flow: Inspect issue -> layer 3, then layer 4 when the steps are ready
   ==================================================================== */
export function loadingBlock(lines = 3) {
  return h("div", { class: "space-y-3", "aria-busy": "true" }, ...Array.from({ length: lines }, (_, i) => h("div", { class: "skeleton h-6", style: `width:${100 - i * 14}%` })));
}

export const errorBlock = (prefix, message) =>
  h("p", { class: "rounded-xl border border-rose-700/40 bg-rose-600/10 p-3 text-sm text-rose-900", role: "alert", text: `${prefix} ${message}` });

export function markSelected() {
  document.querySelectorAll("#issue-groups [data-issue-id]").forEach((card) => card.setAttribute("aria-current", String(card.dataset.issueId === state.selectedId)));
}

export function setStepsReady(ready) {
  $("to-steps").setAttribute("aria-disabled", String(!ready));
  $("to-steps-label").textContent = ready ? "Show me the steps" : "Preparing your steps...";
}

/** The plan layer 4 shows: the issue's own details plus the checklist the server built from its URL. */
export function buildPlan(issue, checklist) {
  return {
    issue_id: issue.id,
    title: issue.title,
    repo_full_name: checklist.repo_full_name,
    github_issue_url: issue.github_issue_url,
    contributing_guidelines_url: issue.contributing_guidelines_url || issue.github_issue_url,
    context_summary: issue.context_summary || "",
    actionable_checklist: checklist.actionable_checklist,
  };
}

/** The repository's own rules arrive last: reading the guide is the slowest part and the page works without it. */
async function loadGuide(token, url) {
  try {
    const guide = await postJson("/api/guide", url);
    if (token === selectionToken) renderGuide(guide.highlights);
  } catch { /* a bonus, never an error */ }
}

/** `issue` may be a list summary or just a bookmark record; the live check below fills in the rest. */
export async function selectIssue(issue) {
  const token = ++selectionToken;
  state.selectedId = issue.id;
  state.verification = null;
  state.plan = null;
  markSelected();

  if (issue.context_summary) renderUnderstand(issue);
  else $("understand-panel").replaceChildren(loadingBlock(4));
  renderApproach(issue.context_summary ? issue : null);
  $("check-panel").replaceChildren(loadingBlock());
  $("start-panel").replaceChildren(loadingBlock(5));
  setStepsReady(false);
  goLayer(3);

  // Both calls start now. The steps need no GitHub call, so they come back at once and survive a GitHub rate limit.
  const params = new URLSearchParams({ github_url: issue.github_issue_url });
  if (issue.programming_language) params.set("language", issue.programming_language);
  const stepsRequest = api(`/api/checklist?${params}`);
  const verifyRequest = postJson("/api/verify", issue.github_issue_url);

  try {
    const checklist = await stepsRequest;
    if (token !== selectionToken) return;
    registerIssue({ id: issue.id, actionable_checklist: checklist.actionable_checklist });
    state.plan = buildPlan(issue, checklist);
    renderPlan();
  } catch (error) {
    if (token !== selectionToken) return;
    $("start-panel").replaceChildren(errorBlock("Could not build your steps.", error.message));
  }
  setStepsReady(true); // on failure layer 4 shows the error, with a way back

  try {
    const verification = await verifyRequest;
    if (token !== selectionToken) return;
    state.verification = verification;
    registerIssue(verification.issue);
    renderUnderstand(verification.issue); // the live check has the freshest details
    renderApproach(verification.issue);
    renderCheck();
    // The plan panel shows a warning for blocked issues; refresh it only if there is one to show.
    if (state.plan && verification.health_state === "blocked") renderPlan();
    loadGuide(token, issue.github_issue_url);
  } catch (error) {
    if (token !== selectionToken) return;
    $("check-panel").replaceChildren(errorBlock("Could not check this issue.", error.message));
    if (!issue.context_summary) {
      $("understand-panel").replaceChildren(errorBlock("Could not load this issue.", error.message));
      $("approach-panel").replaceChildren();
    }
  }
}
