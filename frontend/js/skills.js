import { h, slug } from "./dom.js";
import { $, SKILLS_KEY, state } from "./state.js";
import { LANGUAGE_DOT, plural } from "./ui.js";

/* ====================================================================
   LAYER 1: skills
   ==================================================================== */
export const TOPIC_LABEL = {
  documentation: "Writing docs",
  testing: "Writing tests",
  bug: "Fixing bugs",
  cli: "Command-line tools",
  api: "APIs",
  ui: "UI and front-end",
  accessibility: "Accessibility",
  performance: "Performance",
  refactor: "Cleaning up code",
  security: "Security",
  typing: "Type annotations",
};
export const NOT_A_SKILL = new Set(["help wanted"]); // a GitHub label, not something a person knows
export const skillLabel = (name) => TOPIC_LABEL[name] || name;

// How each skill shows up in an issue's labels, title and description.
export const TOPIC_PATTERN = {
  documentation: /\b(docs?|documentation|readme|typos?|spelling)\b/i,
  testing: /\b(tests?|testing|pytest|jest|coverage|flaky)\b/i,
  bug: /\b(bugs?|fix(?:es)?|crash(?:es)?|errors?|broken|regression)\b/i,
  cli: /\b(cli|command[- ]line|terminal)\b/i,
  api: /\b(apis?|endpoints?|rest|graphql|http)\b/i,
  ui: /\b(ui|front-?end|css|layout|button|component)\b/i,
  accessibility: /\b(accessib\w*|a11y|aria|screen[- ]reader|contrast)\b/i,
  performance: /\b(perf\w*|slow|speed|latency|memory)\b/i,
  refactor: /\b(refactor\w*|clean ?up|tech[- ]debt|simplif\w*)\b/i,
  security: /\b(security|vulnerab\w*|cve|xss|csrf)\b/i,
  typing: /\b(typing|type hints?|mypy|annotations?)\b/i,
};
export function topicRegex(name) {
  return TOPIC_PATTERN[name] || new RegExp(`\\b${name.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}\\b`, "i");
}

export function loadSkills() {
  try {
    const raw = JSON.parse(localStorage.getItem(SKILLS_KEY) || "{}");
    const list = (value) => new Set(Array.isArray(value) ? value.filter((item) => typeof item === "string") : []);
    return { languages: list(raw.languages), topics: list(raw.topics) };
  } catch {
    return { languages: new Set(), topics: new Set() };
  }
}

export function saveSkills() {
  try {
    localStorage.setItem(SKILLS_KEY, JSON.stringify({ languages: [...state.skills.languages], topics: [...state.skills.topics] }));
  } catch { /* storage unavailable: skills last for this page view only */ }
}

export const skillCount = () => state.skills.languages.size + state.skills.topics.size;

export function skillChip(kind, name) {
  const id = `skill-${kind}-${slug(name)}`;
  const input = h("input", { type: "checkbox", class: "cb", id, value: name, checked: state.skills[kind].has(name) });
  input.addEventListener("change", () => {
    if (input.checked) state.skills[kind].add(name);
    else state.skills[kind].delete(name);
    saveSkills();
    renderSkillSummary();
  });
  return h(
    "label",
    { class: "skill-chip", for: id },
    input,
    kind === "languages" ? h("span", { class: `h-2 w-2 rounded-full ${LANGUAGE_DOT[name] || "bg-ink-muted"}`, "aria-hidden": "true" }) : null,
    h("span", { text: kind === "topics" ? skillLabel(name) : name })
  );
}

export function renderSkills() {
  $("skill-languages").replaceChildren(...state.facets.languages.map((name) => skillChip("languages", name)));
  $("skill-topics").replaceChildren(...state.facets.topics.filter((name) => !NOT_A_SKILL.has(name)).map((name) => skillChip("topics", name)));
  renderSkillSummary();
}

export function renderSkillSummary() {
  const n = skillCount();
  $("skill-summary").textContent = n
    ? `${plural(n, "skill")} selected.`
    : "Nothing selected yet. That is fine: you can skip this and start with the easiest issues.";
  $("continue-label").textContent = n ? "Find issues that match my skills" : "Skip: show me the easiest issues";
  $("clear-skills").hidden = n === 0;
}

export function clearSkills() {
  state.skills.languages.clear();
  state.skills.topics.clear();
  saveSkills();
  renderSkills();
}
