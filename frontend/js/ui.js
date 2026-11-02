import { h } from "./dom.js";

/* ====================================================================
   Formatting and shared pieces
   ==================================================================== */
export const TONE_CLASS = {
  good: "border-emerald-700/50 bg-emerald-600/15 text-emerald-900",
  warn: "border-amber-700/50 bg-amber-500/20 text-amber-900",
  bad: "border-rose-700/50 bg-rose-600/15 text-rose-900",
  info: "border-teal-700/40 bg-teal-600/10 text-teal-900",
};

/** Status pill. Healthy (good) pills carry a pulsing indicator dot. */
export function badge(label, tone) {
  return h(
    "span",
    { class: `inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-xs font-semibold ${TONE_CLASS[tone]}` },
    h("span", { class: `h-1.5 w-1.5 rounded-full bg-current ${tone === "good" ? "animate-pulse" : ""}`, "aria-hidden": "true" }),
    label
  );
}

export const LANGUAGE_DOT = {
  Python: "bg-sky-600",
  JavaScript: "bg-yellow-500",
  TypeScript: "bg-blue-600",
  Go: "bg-cyan-600",
  Rust: "bg-orange-500",
};

// Cards only know when GitHub last touched the issue (bots and labels count). The Check panel
// reads the real last comment, so it uses the stronger words Active, Slowing down and Stale.
export const ACTIVITY = {
  active: { label: "Updated recently", tone: "good" },
  slow: { label: "Updated a while ago", tone: "warn" },
  stale: { label: "Not updated lately", tone: "bad" },
};

export const DIFFICULTY_LABEL = ["", "Very easy", "Easy", "Moderate", "Hard", "Expert"];

export function difficultyMeter(rating) {
  return h(
    "span",
    { class: "inline-flex items-center gap-1", role: "img", "aria-label": `Difficulty ${rating} of 5, ${DIFFICULTY_LABEL[rating]}` },
    [1, 2, 3, 4, 5].map((n) =>
      h("span", { class: `h-1.5 w-3.5 rounded-full ${n <= rating ? "bg-teal" : "bg-line/20"}`, "aria-hidden": "true" })
    ),
    h("span", { class: "ml-1.5 text-xs text-ink-muted", text: DIFFICULTY_LABEL[rating] })
  );
}

export function languagePill(language) {
  return h(
    "span",
    { class: "inline-flex items-center gap-2 text-sm font-medium text-ink" },
    h("span", { class: `h-2.5 w-2.5 rounded-full ${LANGUAGE_DOT[language] || "bg-ink-muted"}`, "aria-hidden": "true" }),
    language
  );
}

export const monoLabel = (text, extra = "", title = "") => h("span", { class: `mono-label ${extra}`, title: title || null, text });

/** Keep long repository paths on one line: show the last two segments, full path on hover. */
export function shortPath(path, max = 34) {
  if (path.length <= max) return path;
  return `…/${path.split("/").slice(-2).join("/")}`;
}

export function formatDate(isoDate) {
  const date = new Date(`${String(isoDate).slice(0, 10)}T00:00:00`);
  return Number.isNaN(date.getTime())
    ? String(isoDate)
    : date.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
}

export function daysAgo(isoDate) {
  const days = Math.max(0, Math.round((Date.now() - new Date(`${String(isoDate).slice(0, 10)}T00:00:00`).getTime()) / 86400000));
  if (Number.isNaN(days)) return "";
  return days === 0 ? "today" : days === 1 ? "1 day ago" : `${days} days ago`;
}

export const plural = (n, word) => `${n} ${word}${n === 1 ? "" : "s"}`;
