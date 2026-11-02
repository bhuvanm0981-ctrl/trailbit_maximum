import { h, richText } from "./dom.js";
import { arrowIcon } from "./layers.js";
import { focusCurrentStep } from "./plan.js";
import { countDone, isDone, paintRow, toggleStep, totalSteps } from "./progress.js";

/* ====================================================================
   Checklist rows (used on cards and in the Get started panel)
   ==================================================================== */
export function stepRow(issueId, step, scope) {
  const finished = isDone(issueId, step.step_number);
  const inputId = `${scope}-${issueId}-${step.step_number}`;
  const input = h("input", {
    type: "checkbox",
    class: "cb",
    id: inputId,
    "data-issue": issueId,
    "data-step": step.step_number,
    checked: finished,
  });
  const text = h("span", { class: "step-text" }, richText(step.task));
  const row = h(
    "label",
    { class: "step-row", for: inputId },
    input,
    h(
      "span",
      { class: "min-w-0 flex-1" },
      h("span", { class: "mr-2 font-mono text-xs text-ink-muted", "aria-hidden": "true", text: String(step.step_number).padStart(2, "0") }),
      h("span", { class: "sr-only", text: `Step ${step.step_number}: ` }),
      text
    )
  );
  paintRow(row, finished);
  input.addEventListener("change", () => {
    toggleStep(issueId, step.step_number, input.checked);
    if (input.checked) {
      row.classList.remove("check-pop");
      void row.offsetWidth; // restart the flash if the same row is ticked twice quickly
      row.classList.add("check-pop");
    }
  });
  if (scope !== "plan") return h("li", {}, row);

  // Layer 4: the current step carries a button that ticks it and moves on to the next one.
  const next = h("button", {
    type: "button",
    class: "btn",
    hidden: true,
    "data-next-step": step.step_number,
    onClick: () => {
      toggleStep(issueId, step.step_number, true);
      row.classList.remove("check-pop");
      void row.offsetWidth;
      row.classList.add("check-pop");
      focusCurrentStep();
    },
  }, "Done, next step", arrowIcon());
  return h("li", { class: "plan-step", "data-plan-step": step.step_number }, row, h("div", { class: "step-actions" }, next));
}

export function progressBlock(issue) {
  const total = totalSteps(issue.id);
  const done = countDone(issue.id);
  return h(
    "div",
    { class: "space-y-1.5" },
    h(
      "div",
      { class: "flex items-center justify-between text-xs text-ink-muted" },
      h("span", { text: "Checklist progress" }),
      h("span", { "data-issue": issue.id, "data-count": "1", class: "tabular-nums", text: `${done} of ${total} steps` })
    ),
    h("div", { class: "progress-mini" }, h("span", { "data-issue": issue.id, "data-fill": "1", style: `width:${total ? Math.round((done / total) * 100) : 0}%` }))
  );
}
