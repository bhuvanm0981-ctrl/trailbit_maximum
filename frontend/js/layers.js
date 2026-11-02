import { ensureIssues } from "./issues.js";
import { $, SVG_NS, state } from "./state.js";

/* ====================================================================
   LAYERS: Your skills -> Pick an issue -> The problem -> Resolve it
   ==================================================================== */
export const LAYERS = [
  { n: 1, name: "Your skills" },
  { n: 2, name: "Pick an issue" },
  { n: 3, name: "The problem" },
  { n: 4, name: "Resolve it" },
];

export const motion = () => (window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth");

export function arrowIcon() {
  const svg = document.createElementNS(SVG_NS, "svg");
  svg.setAttribute("viewBox", "0 0 24 24");
  svg.setAttribute("class", "arrow h-4 w-4");
  svg.setAttribute("aria-hidden", "true");
  svg.setAttribute("fill", "none");
  svg.setAttribute("stroke", "currentColor");
  svg.setAttribute("stroke-width", "2.2");
  svg.setAttribute("stroke-linecap", "round");
  svg.setAttribute("stroke-linejoin", "round");
  const path = document.createElementNS(SVG_NS, "path");
  path.setAttribute("d", "M5 12h14M13 6l6 6-6 6");
  svg.appendChild(path);
  return svg;
}

/** Layers 1 and 2 are always open; the problem and the steps need an issue to be chosen first. */
export function canEnter(n) {
  return n <= 2 || Boolean(state.selectedId);
}

export function paintStepper() {
  document.querySelectorAll("#stepper button[data-layer]").forEach((button) => {
    const n = Number(button.dataset.layer);
    const item = button.closest("li");
    const enabled = canEnter(n);
    button.setAttribute("aria-disabled", String(!enabled));
    if (enabled) button.removeAttribute("title");
    else button.title = "Choose an issue first";
    item.classList.toggle("is-current", n === state.layer);
    item.classList.toggle("is-done", n < state.layer);
    if (n === state.layer) button.setAttribute("aria-current", "step");
    else button.removeAttribute("aria-current");
  });
}

/** Show one layer. `push` adds a browser-history entry so Back and Forward walk through the layers. */
export function goLayer(target, { push = true, focus = true } = {}) {
  // A hand-typed #step-9 or #step-0 is not a layer: stay within the four that exist.
  const wanted = Number.isInteger(target) ? Math.min(Math.max(target, 1), LAYERS.length) : 1;
  const n = canEnter(wanted) ? wanted : 2;
  const direction = n >= state.layer ? "forward" : "back";
  state.layer = n;

  document.querySelectorAll(".layer").forEach((section) => {
    const active = Number(section.dataset.layer) === n;
    section.hidden = !active;
    section.classList.remove("layer-forward", "layer-back");
    if (active) {
      void section.offsetWidth; // restart the entrance animation
      section.classList.add(`layer-${direction}`);
    }
  });
  paintStepper();

  try {
    const hash = `#step-${n}`;
    if (location.hash !== hash) {
      if (push) history.pushState({ layer: n }, "", hash);
      else history.replaceState({ layer: n }, "", hash);
    }
  } catch { /* history is unavailable in some embedded contexts */ }

  $("layer-live").textContent = `Step ${n} of ${LAYERS.length}: ${LAYERS[n - 1].name}`;
  if (focus) {
    const title = $(`layer-${n}`).querySelector("[data-layer-title]");
    if (title) title.focus({ preventScroll: true });
    $("stepper-wrap").scrollIntoView({ behavior: motion(), block: "start" });
  }
  if (n === 2) ensureIssues();
}
