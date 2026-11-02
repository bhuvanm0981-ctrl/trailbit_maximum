import { externalLink, h } from "./dom.js";
import { arrowIcon, goLayer, motion } from "./layers.js";
import { registerIssue } from "./progress.js";
import { $, state } from "./state.js";
import { progressBlock, stepRow } from "./steps.js";
import { monoLabel } from "./ui.js";

/* ====================================================================
   LAYER 4: step by step
   ==================================================================== */
export function renderPlan() {
  const plan = state.plan;
  if (!plan) return;
  let issue = state.byId.get(plan.issue_id);
  if (!issue) {
    issue = { id: plan.issue_id, actionable_checklist: plan.actionable_checklist };
    registerIssue(issue);
  }

  const blocked = state.verification && state.verification.health_state === "blocked";
  $("start-panel").replaceChildren(
    h(
      "div",
      { class: "swap-in space-y-6" },
      h(
        "div",
        { class: "flex flex-wrap items-end justify-between gap-4" },
        h("div", { class: "min-w-0 space-y-2" }, h("h3", { class: "font-display text-xl font-semibold leading-snug text-ink", text: plan.title }), monoLabel(plan.repo_full_name)),
        h("div", { class: "w-full sm:w-64" }, progressBlock(issue))
      ),
      blocked
        ? h("p", { class: "rounded-xl border border-rose-700/40 bg-rose-600/10 p-3 text-sm text-rose-900", role: "note", text: "This issue is blocked: it is locked, closed or in an archived repository. Read the plan, but check the thread before you start coding." })
        : null,
      h("ol", { class: "plan-steps", "aria-label": "Steps to resolve this issue" }, plan.actionable_checklist.map((step) => stepRow(issue.id, step, "plan"))),
      h(
        "div",
        { id: "plan-complete", class: "plan-complete space-y-3", hidden: true },
        h("h3", { id: "plan-complete-title", tabindex: "-1", class: "font-display text-xl font-semibold text-ink", text: "All steps done. Nice work!" }),
        h("p", { class: "text-sm text-ink-body", text: "Once your pull request is open, the maintainers will review it. They may ask for changes. That is normal, and part of the process." }),
        h(
          "div",
          { class: "flex flex-wrap gap-3" },
          externalLink("context-link", plan.github_issue_url, "Open the issue on GitHub"),
          h("button", { type: "button", class: "btn", onClick: () => goLayer(2) }, "Pick another issue", arrowIcon())
        )
      )
    )
  );
  markCurrentStep();
}

/** The first unfinished step is "current": highlighted, with the button that ticks it and moves on. */
export function markCurrentStep() {
  const list = document.querySelector("#start-panel .plan-steps");
  if (!list) return;
  let found = false;
  list.querySelectorAll(":scope > li").forEach((item) => {
    const done = item.querySelector("input[data-step]").checked;
    const current = !done && !found;
    if (current) found = true;
    item.classList.toggle("is-current", current);
    item.classList.toggle("is-upcoming", !done && !current);
    const button = item.querySelector("[data-next-step]");
    if (button) button.hidden = !current;
    if (current) item.setAttribute("aria-current", "step");
    else item.removeAttribute("aria-current");
  });
  const banner = $("plan-complete");
  if (banner) banner.hidden = found;
}

/** After "Done, next step" the button disappears, so hand keyboard focus to the new current step. */
export function focusCurrentStep() {
  const next = document.querySelector("#start-panel .plan-step.is-current input[data-step]");
  if (next) {
    next.focus({ preventScroll: true });
    next.closest("li").scrollIntoView({ behavior: motion(), block: "nearest" });
    return;
  }
  const title = $("plan-complete-title");
  if (title) {
    title.focus({ preventScroll: true });
    title.scrollIntoView({ behavior: motion(), block: "nearest" });
  }
}
