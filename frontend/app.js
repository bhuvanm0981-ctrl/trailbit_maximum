/* Trailbit frontend: four layers, one at a time.
     1 Your skills     what Trailbit is, how to use it, and a skills checklist (saved in localStorage).
     2 Pick an issue   GET /api/issues once, then ranked in the browser by how well each issue matches the skills:
                       best matches first, fading to less related ones. Changing skills re-ranks without new calls.
     3 The problem     Inspect issue -> POST /api/verify (health) + the issue's own description + a typical approach.
     4 Resolve it      POST /api/plan -> a step-by-step checklist with one current step.
   Bookmarks -> /api/bookmarks (SQLite), toggled from every card and mirrored on every screen.
   One progress store (state.progress) drives every checkbox, every card, the plan and the global bar. */
"use strict";

// Same-origin when served by the backend; fall back to the local server when opened from disk.
const API_BASE = window.location.protocol === "file:" ? "http://127.0.0.1:8000" : "";
const PROGRESS_PREFIX = "trailbit:progress:";
const SKILLS_KEY = "trailbit:skills";
const SEARCH_DEBOUNCE_MS = 350;
const LEAVE_ANIMATION_MS = 220;
const TOAST_MS = 3200;
const SVG_NS = "http://www.w3.org/2000/svg";
const STAR_PATH = "M12 3.5l2.6 5.3 5.9.9-4.3 4.1 1 5.8L12 16.9 6.8 19.6l1-5.8L3.5 9.7l5.9-.9L12 3.5z";

const state = {
  layer: 1,               // which of the four layers is showing
  skills: { languages: new Set(), topics: new Set() },
  q: "",                  // free-text search on layer 2
  facets: { languages: [], topics: [] },
  pool: [],               // every issue fetched for the current search, unranked
  poolReady: false,
  poolQuery: null,        // the search text the pool was fetched for
  loading: false,
  issues: [],             // the pool ranked by skills match (drives the progress bar)
  rel: new Map(),         // id -> how well that issue matches the skills (null when no skills are picked)
  byId: new Map(),        // id -> issue (or a minimal record) for every issue seen this session
  progress: new Map(),    // id -> Set of completed step numbers (mirrors localStorage)
  bookmarks: new Map(),   // id -> bookmark record from /api/bookmarks
  pendingBookmarks: new Set(),
  view: "workspace",
  selectedId: null,
  verification: null,
  plan: null,
};

let listToken = 0;
let listController = null;
let selectionToken = 0;
let searchTimer = null;
let toastTimer = null;

const $ = (id) => document.getElementById(id);
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

/* ====================================================================
   DOM helpers (text always goes through textContent / text nodes)
   ==================================================================== */
function h(tag, props = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(props)) {
    if (value === undefined || value === null || value === false) continue;
    if (key === "class") node.className = value;
    else if (key === "text") node.textContent = value;
    else if (key.startsWith("on") && typeof value === "function") node.addEventListener(key.slice(2).toLowerCase(), value);
    else if (key === "checked" || key === "disabled") node[key] = Boolean(value);
    else node.setAttribute(key, value === true ? "" : String(value));
  }
  for (const child of children.flat()) {
    if (child === undefined || child === null || child === false) continue;
    node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return node;
}

/** Turn `inline code` in a plain string into <code> elements without using innerHTML. */
function richText(text) {
  return String(text)
    .split(/(`[^`]+`)/g)
    .filter(Boolean)
    .map((part) =>
      part.startsWith("`") && part.endsWith("`") && part.length > 2 ? h("code", { text: part.slice(1, -1) }) : part
    );
}

function safeHref(url) {
  try {
    const parsed = new URL(url);
    return parsed.protocol === "https:" ? parsed.href : "#";
  } catch {
    return "#";
  }
}

/** Link that opens in a new tab, with that said out loud to screen-reader users. */
function externalLink(className, url, label) {
  return h(
    "a",
    { class: className, href: safeHref(url), target: "_blank", rel: "noopener noreferrer" },
    label,
    h("span", { class: "sr-only", text: " (opens in a new tab)" })
  );
}

const slug = (value) => String(value).toLowerCase().replace(/[^a-z0-9]+/g, "-");

function eachForIssue(selector, issueId, fn) {
  document.querySelectorAll(selector).forEach((node) => {
    if (node.dataset.issue === issueId) fn(node);
  });
}

function starIcon(filled = false) {
  const svg = document.createElementNS(SVG_NS, "svg");
  svg.setAttribute("viewBox", "0 0 24 24");
  svg.setAttribute("class", `bookmark-icon${filled ? " is-filled" : ""}`);
  svg.setAttribute("aria-hidden", "true");
  const path = document.createElementNS(SVG_NS, "path");
  path.setAttribute("d", STAR_PATH);
  path.setAttribute("stroke-linejoin", "round");
  svg.appendChild(path);
  return svg;
}

/* ====================================================================
   API
   ==================================================================== */
async function api(path, options = {}) {
  let response;
  try {
    response = await fetch(`${API_BASE}${path}`, { headers: { "Content-Type": "application/json" }, ...options });
  } catch (error) {
    if (error && error.name === "AbortError") throw error;
    throw new Error("Could not reach the Trailbit server. Start it on port 8000 and reload this page.");
  }
  if (!response.ok) {
    let detail = `The server returned an error (${response.status}).`;
    try {
      const body = await response.json();
      if (typeof body.detail === "string") detail = body.detail;
      else if (Array.isArray(body.detail) && body.detail[0]?.msg) detail = body.detail[0].msg;
    } catch { /* keep the generic message */ }
    const error = new Error(detail);
    error.status = response.status;
    throw error;
  }
  return response.json();
}

function fetchIssues(filters, signal) {
  const query = new URLSearchParams();
  filters.language.forEach((value) => query.append("language", value));
  filters.topic.forEach((value) => query.append("topic", value));
  if (filters.q.trim()) query.set("q", filters.q.trim());
  const suffix = query.toString();
  return api(`/api/issues${suffix ? `?${suffix}` : ""}`, { signal });
}

const postJson = (path, githubUrl) =>
  api(path, { method: "POST", body: JSON.stringify({ github_url: githubUrl }) });

/* ====================================================================
   Toast
   ==================================================================== */
function showToast(message, kind = "info") {
  const toast = $("toast");
  toast.textContent = message;
  toast.className = `toast show${kind === "error" ? " error" : ""}`;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => toast.classList.remove("show"), TOAST_MS);
}

/* ====================================================================
   Progress store: Map(issueId -> Set(stepNumber)), persisted per issue in localStorage
   ==================================================================== */
function loadProgress(issueId) {
  try {
    const parsed = JSON.parse(localStorage.getItem(PROGRESS_PREFIX + issueId) || "[]");
    return new Set(Array.isArray(parsed) ? parsed.filter(Number.isInteger) : []);
  } catch {
    return new Set();
  }
}

function saveProgress(issueId) {
  try {
    const steps = [...progressFor(issueId)].sort((a, b) => a - b);
    localStorage.setItem(PROGRESS_PREFIX + issueId, JSON.stringify(steps));
  } catch { /* storage unavailable: progress lasts for this page view only */ }
}

function progressFor(issueId) {
  if (!state.progress.has(issueId)) state.progress.set(issueId, loadProgress(issueId));
  return state.progress.get(issueId);
}

const isDone = (issueId, stepNumber) => progressFor(issueId).has(stepNumber);

function countDone(issue) {
  const set = progressFor(issue.id);
  return issue.actionable_checklist.filter((step) => set.has(step.step_number)).length;
}

function registerIssue(issue) {
  if (issue && issue.id && Array.isArray(issue.actionable_checklist)) state.byId.set(issue.id, issue);
}

function toggleStep(issueId, stepNumber, checked) {
  const set = progressFor(issueId);
  if (checked) set.add(stepNumber);
  else set.delete(stepNumber);
  saveProgress(issueId);
  syncIssue(issueId);
}

/** Repaint every place that shows this issue's progress. No re-render, so open cards stay open. */
function syncIssue(issueId) {
  const issue = state.byId.get(issueId);
  if (!issue) return;
  const total = issue.actionable_checklist.length;
  const done = countDone(issue);
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

function paintRow(row, finished) {
  if (!row) return;
  row.classList.toggle("is-done", finished);
  const text = row.querySelector(".step-text");
  // Inline decoration as well as the stylesheet rule, so the strike-through always follows the checkbox.
  if (text) text.style.textDecoration = finished ? "line-through" : "none";
}

/** The bar covers the checklists of the issues currently on screen. */
function renderGlobalProgress() {
  const issues = state.issues;
  const total = issues.reduce((sum, issue) => sum + issue.actionable_checklist.length, 0);
  const done = issues.reduce((sum, issue) => sum + countDone(issue), 0);
  const finished = issues.filter((issue) => countDone(issue) === issue.actionable_checklist.length).length;
  const percent = total ? Math.round((done / total) * 100) : 0;

  $("progress-label").textContent = `Onboarding Progress: ${percent}% Complete`;
  $("progress-fill").style.width = `${percent}%`;
  const bar = $("progress-bar");
  bar.setAttribute("aria-valuenow", String(percent));
  // A bare "42" is meaningless to a screen reader; valuetext says what the number measures.
  bar.setAttribute("aria-valuetext", total ? `${percent}% complete, ${done} of ${total} steps done` : "No steps loaded yet");
  bar.classList.toggle("is-complete", total > 0 && done === total);
  $("progress-detail").textContent = total
    ? `${done} of ${total} steps done, ${finished} of ${issues.length} issues finished`
    : "Progress appears here once issues load.";
}

/* ====================================================================
   Formatting and shared pieces
   ==================================================================== */
const TONE_CLASS = {
  good: "border-emerald-500/50 bg-emerald-500/20 text-emerald-400 shadow-[0_0_14px_rgba(16,185,129,0.25)]",
  warn: "border-amber-500/50 bg-amber-500/15 text-amber-400",
  bad: "border-rose-500/50 bg-rose-500/15 text-rose-400",
  info: "border-amber-300/40 bg-amber-300/10 text-amber-100",
};

/** Status pill. Healthy (good) pills carry a pulsing indicator dot. */
function badge(label, tone) {
  return h(
    "span",
    { class: `inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-xs font-semibold ${TONE_CLASS[tone]}` },
    h("span", { class: `h-1.5 w-1.5 rounded-full bg-current ${tone === "good" ? "animate-pulse" : ""}`, "aria-hidden": "true" }),
    label
  );
}

const LANGUAGE_DOT = {
  Python: "bg-sky-400",
  JavaScript: "bg-yellow-300",
  TypeScript: "bg-blue-500",
  Go: "bg-cyan-300",
  Rust: "bg-orange-400",
};

// Cards only know when GitHub last touched the issue (bots and labels count). The Check panel
// reads the real last comment, so it uses the stronger words Active, Slowing down and Stale.
const ACTIVITY = {
  active: { label: "Updated recently", tone: "good" },
  slow: { label: "Updated a while ago", tone: "warn" },
  stale: { label: "Not updated lately", tone: "bad" },
};

const DIFFICULTY_LABEL = ["", "Very easy", "Easy", "Moderate", "Hard", "Expert"];

function difficultyMeter(rating) {
  return h(
    "span",
    { class: "inline-flex items-center gap-1", role: "img", "aria-label": `Difficulty ${rating} of 5, ${DIFFICULTY_LABEL[rating]}` },
    [1, 2, 3, 4, 5].map((n) =>
      h("span", { class: `h-1.5 w-3.5 rounded-full ${n <= rating ? "bg-[#ffc940]" : "bg-slate-800"}`, "aria-hidden": "true" })
    ),
    h("span", { class: "ml-1.5 text-xs text-slate-400", text: DIFFICULTY_LABEL[rating] })
  );
}

function languagePill(language) {
  return h(
    "span",
    { class: "inline-flex items-center gap-2 text-sm font-medium text-slate-200" },
    h("span", { class: `h-2.5 w-2.5 rounded-full ${LANGUAGE_DOT[language] || "bg-slate-400"}`, "aria-hidden": "true" }),
    language
  );
}

const monoLabel = (text, extra = "", title = "") => h("span", { class: `mono-label ${extra}`, title: title || null, text });

/** Keep long repository paths on one line: show the last two segments, full path on hover. */
function shortPath(path, max = 34) {
  if (path.length <= max) return path;
  return `…/${path.split("/").slice(-2).join("/")}`;
}

function formatDate(isoDate) {
  const date = new Date(`${String(isoDate).slice(0, 10)}T00:00:00`);
  return Number.isNaN(date.getTime())
    ? String(isoDate)
    : date.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
}

function daysAgo(isoDate) {
  const days = Math.max(0, Math.round((Date.now() - new Date(`${String(isoDate).slice(0, 10)}T00:00:00`).getTime()) / 86400000));
  if (Number.isNaN(days)) return "";
  return days === 0 ? "today" : days === 1 ? "1 day ago" : `${days} days ago`;
}

const plural = (n, word) => `${n} ${word}${n === 1 ? "" : "s"}`;

/* ====================================================================
   Bookmarks
   ==================================================================== */
/** `beforeToggle` may return a promise; the toggle waits for it (used to fade a card out first). */
function bookmarkButton(issue, { beforeToggle = null } = {}) {
  const button = h(
    "button",
    {
      type: "button",
      class: "bookmark-btn",
      "data-bookmark-id": issue.id,
      "data-title": issue.title,
      onClick: async (event) => {
        event.stopPropagation();
        if (beforeToggle) await beforeToggle();
        toggleBookmark(issue);
      },
    },
    starIcon()
  );
  paintBookmark(button, state.bookmarks.has(issue.id), false);
  return button;
}

function paintBookmark(button, saved, animate) {
  const was = button.getAttribute("aria-pressed") === "true";
  const label = saved ? "Remove bookmark" : "Save bookmark";
  button.setAttribute("aria-pressed", String(saved));
  // The accessible name stays constant: aria-pressed already announces the saved state, and a name that
  // also flips ("Save"/"Remove") would read as a contradiction ("Save bookmark, pressed"). Sighted users get the tooltip.
  button.setAttribute("aria-label", `Bookmark: ${button.dataset.title}`);
  button.title = label;
  button.classList.toggle("is-saved", saved);
  if (animate && was !== saved) {
    button.classList.remove("pop");
    void button.offsetWidth; // restart the animation
    button.classList.add("pop");
  }
}

/** Repaint every star, the header count and the Bookmarks view from state.bookmarks. */
function syncBookmarks({ animate = false } = {}) {
  document.querySelectorAll("[data-bookmark-id]").forEach((button) => {
    paintBookmark(button, state.bookmarks.has(button.dataset.bookmarkId), animate);
  });

  const count = state.bookmarks.size;
  const pill = $("bookmark-count");
  const previous = pill.textContent;
  pill.textContent = String(count);
  pill.hidden = count === 0;
  if (animate && previous !== String(count)) {
    pill.classList.remove("bump");
    void pill.offsetWidth;
    pill.classList.add("bump");
  }
  renderBookmarksView();
}

async function toggleBookmark(issue) {
  const id = issue.id;
  if (state.pendingBookmarks.has(id)) return;
  state.pendingBookmarks.add(id);

  const wasSaved = state.bookmarks.has(id);
  const previous = state.bookmarks.get(id);
  // Update the screen first so the star responds instantly; undo below if the server says no.
  if (wasSaved) state.bookmarks.delete(id);
  else {
    state.bookmarks.set(id, {
      id,
      title: issue.title,
      repo_name: issue.repo_name,
      repo_owner: issue.repo_owner,
      programming_language: issue.programming_language,
      github_issue_url: issue.github_issue_url,
      bookmarked_at: new Date().toISOString(),
    });
  }
  syncBookmarks({ animate: true });

  try {
    if (wasSaved) {
      try {
        await api(`/api/bookmarks/${encodeURIComponent(id)}`, { method: "DELETE" });
      } catch (error) {
        if (error.status !== 404) throw error; // already gone on the server: that is the state we wanted
      }
      showToast("Removed from bookmarks");
    } else {
      const saved = await api("/api/bookmarks", { method: "POST", body: JSON.stringify(issue) });
      state.bookmarks.set(id, saved.bookmark);
      showToast("Saved to bookmarks");
    }
  } catch (error) {
    if (wasSaved) state.bookmarks.set(id, previous);
    else state.bookmarks.delete(id);
    showToast(`Could not ${wasSaved ? "remove" : "save"} the bookmark. ${error.message}`, "error");
  } finally {
    state.pendingBookmarks.delete(id);
    syncBookmarks({ animate: true });
  }
}

async function loadBookmarks() {
  try {
    const list = await api("/api/bookmarks");
    state.bookmarks = new Map(list.map((bookmark) => [bookmark.id, bookmark]));
    $("bookmarks-error").classList.add("hidden");
  } catch (error) {
    const box = $("bookmarks-error");
    box.textContent = `Could not load your bookmarks. ${error.message}`;
    box.classList.remove("hidden");
  }
  syncBookmarks();
}

function bookmarkCard(bookmark) {
  const li = h("li", { class: "bookmark-item" });
  // Fade the card out first, then remove it, so unsaving feels like one motion.
  const star = bookmarkButton(bookmark, {
    beforeToggle: () => {
      li.classList.add("is-leaving");
      return sleep(LEAVE_ANIMATION_MS);
    },
  });
  li.append(
    h(
      "article",
      {
        class: "issue-card enter group flex h-full flex-col gap-4 rounded-2xl border border-slate-800/80 p-5 transition duration-300 hover:-translate-y-1.5 hover:border-amber-300/50 hover:shadow-[0_14px_30px_rgba(0,0,0,0.35)]",
        "data-bookmark-card": bookmark.id,
      },
      h("div", { class: "flex items-center justify-between gap-3" }, languagePill(bookmark.programming_language), star),
      h("h3", { class: "font-display text-lg font-semibold leading-snug text-white", text: bookmark.title }),
      h("div", { class: "flex flex-wrap gap-2" }, monoLabel(`${bookmark.repo_owner}/${bookmark.repo_name}`)),
      h("p", { class: "text-xs text-slate-400", text: `Saved ${formatDate(bookmark.bookmarked_at)}` }),
      h(
        "div",
        { class: "mt-auto grid gap-3 sm:grid-cols-2" },
        h("button", { type: "button", class: "btn", text: "Inspect issue", "aria-label": `Inspect issue: ${bookmark.title}`, onClick: () => inspectBookmark(bookmark) }),
        externalLink("context-link", bookmark.github_issue_url, "Open on GitHub")
      )
    )
  );
  return li;
}

function renderBookmarksView() {
  const saved = [...state.bookmarks.values()].sort((a, b) => String(b.bookmarked_at).localeCompare(String(a.bookmarked_at)));
  $("bookmarks-subtitle").textContent = saved.length ? `${plural(saved.length, "saved issue")}, newest first.` : "Nothing saved yet.";
  const grid = $("bookmark-grid");
  if (!saved.length) {
    grid.replaceChildren(
      h(
        "li",
        { class: "glass col-span-full rounded-2xl p-8 text-center" },
        h("p", { class: "font-display text-lg font-semibold text-white", text: "No bookmarks yet" }),
        h("p", { class: "mx-auto mt-1 max-w-md text-sm text-slate-400", text: "Choose the star on any issue to keep it here, even after you close this page." }),
        h("button", { type: "button", class: "btn mt-4", text: "Browse issues", onClick: () => setView("workspace") })
      )
    );
    return;
  }
  grid.replaceChildren(...saved.map(bookmarkCard));
}

function inspectBookmark(bookmark) {
  setView("workspace");
  selectIssue(bookmark);
}

/** `scroll: false` is for callers whose own action already scrolls (nav anchors), so the two do not fight. */
function setView(view, { scroll = true } = {}) {
  const changed = state.view !== view;
  state.view = view;
  const bookmarks = view === "bookmarks";
  $("workspace-view").hidden = bookmarks;
  $("bookmarks-view").hidden = !bookmarks;
  $("view-workspace").setAttribute("aria-pressed", String(!bookmarks));
  $("view-bookmarks").setAttribute("aria-pressed", String(bookmarks));
  try {
    // Keep the address bar linkable: /#bookmarks opens this view directly.
    if (bookmarks) history.replaceState(null, "", "#bookmarks");
    else if (location.hash === "#bookmarks") history.replaceState(null, "", location.pathname + location.search);
  } catch { /* history is unavailable in some embedded contexts */ }
  if (scroll && changed) {
    window.scrollTo({ top: 0, behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth" });
  }
}

/* ====================================================================
   Checklist rows (used on cards and in the Get started panel)
   ==================================================================== */
function stepRow(issueId, step, scope) {
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
      h("span", { class: "mr-2 font-mono text-xs text-amber-200/80", "aria-hidden": "true", text: String(step.step_number).padStart(2, "0") }),
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

function progressBlock(issue) {
  const total = issue.actionable_checklist.length;
  const done = countDone(issue);
  return h(
    "div",
    { class: "space-y-1.5" },
    h(
      "div",
      { class: "flex items-center justify-between text-xs text-slate-400" },
      h("span", { text: "Checklist progress" }),
      h("span", { "data-issue": issue.id, "data-count": "1", class: "tabular-nums", text: `${done} of ${total} steps` })
    ),
    h("div", { class: "progress-mini" }, h("span", { "data-issue": issue.id, "data-fill": "1", style: `width:${total ? Math.round((done / total) * 100) : 0}%` }))
  );
}

/* ====================================================================
   LAYERS: Your skills -> Pick an issue -> The problem -> Resolve it
   ==================================================================== */
const LAYERS = [
  { n: 1, name: "Your skills" },
  { n: 2, name: "Pick an issue" },
  { n: 3, name: "The problem" },
  { n: 4, name: "Resolve it" },
];

const motion = () => (window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth");

function arrowIcon() {
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
function canEnter(n) {
  return n <= 2 || Boolean(state.selectedId);
}

function paintStepper() {
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
function goLayer(target, { push = true, focus = true } = {}) {
  const n = canEnter(target) ? target : 2;
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

/* ====================================================================
   LAYER 1: skills
   ==================================================================== */
const TOPIC_LABEL = {
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
const NOT_A_SKILL = new Set(["help wanted"]); // a GitHub label, not something a person knows
const skillLabel = (name) => TOPIC_LABEL[name] || name;

// How each skill shows up in an issue's labels, title and description.
const TOPIC_PATTERN = {
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
function topicRegex(name) {
  return TOPIC_PATTERN[name] || new RegExp(`\\b${name.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}\\b`, "i");
}

function loadSkills() {
  try {
    const raw = JSON.parse(localStorage.getItem(SKILLS_KEY) || "{}");
    const list = (value) => new Set(Array.isArray(value) ? value.filter((item) => typeof item === "string") : []);
    return { languages: list(raw.languages), topics: list(raw.topics) };
  } catch {
    return { languages: new Set(), topics: new Set() };
  }
}

function saveSkills() {
  try {
    localStorage.setItem(SKILLS_KEY, JSON.stringify({ languages: [...state.skills.languages], topics: [...state.skills.topics] }));
  } catch { /* storage unavailable: skills last for this page view only */ }
}

const skillCount = () => state.skills.languages.size + state.skills.topics.size;

function skillChip(kind, name) {
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
    kind === "languages" ? h("span", { class: `h-2 w-2 rounded-full ${LANGUAGE_DOT[name] || "bg-slate-400"}`, "aria-hidden": "true" }) : null,
    h("span", { text: kind === "topics" ? skillLabel(name) : name })
  );
}

function renderSkills() {
  $("skill-languages").replaceChildren(...state.facets.languages.map((name) => skillChip("languages", name)));
  $("skill-topics").replaceChildren(...state.facets.topics.filter((name) => !NOT_A_SKILL.has(name)).map((name) => skillChip("topics", name)));
  renderSkillSummary();
}

function renderSkillSummary() {
  const n = skillCount();
  $("skill-summary").textContent = n
    ? `${plural(n, "skill")} selected.`
    : "Nothing selected yet. That is fine: you can skip this and start with the easiest issues.";
  $("continue-label").textContent = n ? "Find issues that match my skills" : "Skip: show me the easiest issues";
  $("clear-skills").hidden = n === 0;
}

function clearSkills() {
  state.skills.languages.clear();
  state.skills.topics.clear();
  saveSkills();
  renderSkills();
}

/* ====================================================================
   LAYER 2: rank by relatedness, then render in groups that fade toward "less related"
   ==================================================================== */
/** How well one issue matches the picked skills: a language match is worth 3, each matched area 2 (up to two). */
function relatedness(issue) {
  const languages = [...state.skills.languages];
  const topics = [...state.skills.topics];
  if (!languages.length && !topics.length) return null;

  const haystack = `${issue.topics.join(" ")} ${issue.title} ${issue.context_summary || ""}`;
  const matchedLang = languages.find((language) => language.toLowerCase() === String(issue.programming_language).toLowerCase()) || null;
  const matchedTopics = topics.filter((topic) => topicRegex(topic).test(haystack));

  const best = (languages.length ? 3 : 0) + (topics.length ? 2 * Math.min(topics.length, 2) : 0);
  const score = (matchedLang ? 3 : 0) + 2 * Math.min(matchedTopics.length, 2);
  const percent = best ? Math.round((score / best) * 100) : 0;
  const tier = percent >= 70 ? "best" : percent >= 40 ? "good" : percent > 0 ? "partial" : "stretch";
  return { percent, tier, matchedLang, matchedTopics };
}

const TIERS = [
  { key: "best", title: "Best matches", hint: "Closest to the skills you picked.", dots: 4 },
  { key: "good", title: "Good matches", hint: "They match a good part of what you picked.", dots: 3 },
  { key: "partial", title: "Partial matches", hint: "A smaller overlap with your skills.", dots: 2 },
  { key: "stretch", title: "Outside your skills", hint: "A stretch, but still marked as beginner friendly.", dots: 1 },
];

/** Highest match first; ties go to the easier issue, then to the order GitHub returned. */
function rankIssues(list) {
  state.rel = new Map(list.map((issue) => [issue.id, relatedness(issue)]));
  const percent = (issue) => (state.rel.get(issue.id) ? state.rel.get(issue.id).percent : 0);
  return list
    .map((issue, index) => ({ issue, index }))
    .sort((a, b) => percent(b.issue) - percent(a.issue) || a.issue.difficulty_rating - b.issue.difficulty_rating || a.index - b.index)
    .map((entry) => entry.issue);
}

function groupIssues(ranked) {
  if (!skillCount()) {
    return [{ key: "easy", title: "Easiest to start with", hint: "You did not pick skills, so these run from the easiest to the hardest.", dots: 4, issues: ranked }];
  }
  return TIERS.map((tier) => ({ ...tier, issues: ranked.filter((issue) => state.rel.get(issue.id).tier === tier.key) })).filter((group) => group.issues.length);
}

function matchLine(rel) {
  const names = [rel.matchedLang, ...rel.matchedTopics.map(skillLabel)].filter(Boolean);
  return h(
    "div",
    { class: "flex flex-wrap items-center gap-x-3 gap-y-1.5" },
    h("span", { class: `match-pill match-${rel.tier}` }, h("span", { class: "match-bar", "aria-hidden": "true" }, h("i", { style: `width:${rel.percent}%` })), `${rel.percent}% match`),
    names.length ? h("span", { class: "text-xs text-slate-300", text: `Matches: ${names.join(", ")}` }) : null
  );
}

function issueCard(issue, index, animate) {
  const metrics = issue.status_metrics;
  const activity = ACTIVITY[metrics.activity_indicator] || ACTIVITY.slow;
  const titleId = `title-${issue.id}`;
  const closed = issue.state === "closed";
  const rel = state.rel.get(issue.id);

  return h(
    "li",
    {},
    h(
      "article",
      {
        class: `issue-card ${animate ? "enter" : ""} group flex h-full flex-col gap-4 rounded-2xl border border-slate-800/80 p-5 transition duration-300 hover:-translate-y-1.5 hover:border-amber-300/50 hover:shadow-[0_14px_30px_rgba(0,0,0,0.35)]`,
        style: animate ? `animation-delay:${Math.min(index, 11) * 45}ms` : null,
        "data-issue-id": issue.id,
        "aria-labelledby": titleId,
        "aria-current": String(issue.id === state.selectedId),
      },
      h(
        "div",
        { class: "flex items-center justify-between gap-3" },
        languagePill(issue.programming_language),
        h("div", { class: "flex items-center gap-3" }, difficultyMeter(issue.difficulty_rating), bookmarkButton(issue))
      ),
      h("h4", { id: titleId, class: "font-display text-lg font-semibold leading-snug text-white", text: issue.title }),
      rel && rel.percent > 0 ? matchLine(rel) : null,
      h(
        "div",
        { class: "flex flex-wrap gap-2" },
        monoLabel(`${issue.repo_owner}/${issue.repo_name}`),
        issue.active_handles.slice(0, 3).map((handle) => monoLabel(`@${handle}`, "mono-handle"))
      ),
      issue.affected_paths.length
        ? h(
            "ul",
            { class: "flex flex-col gap-1.5", "aria-label": "Files this change touches" },
            issue.affected_paths.slice(0, 2).map((path) => h("li", {}, monoLabel(shortPath(path), "inline-block text-slate-400", path)))
          )
        : null,
      issue.topics.length
        ? h("div", { class: "flex flex-wrap gap-1.5" }, issue.topics.map((topic) => h("span", { class: "rounded-md bg-slate-800/70 px-2 py-0.5 text-xs text-slate-300", text: topic })))
        : null,
      h(
        "div",
        { class: "mt-auto space-y-4" },
        h(
          "div",
          { class: "flex flex-wrap items-center gap-2 border-t border-slate-800/60 pt-4" },
          badge(closed ? "Closed" : metrics.is_locked ? "Locked" : "Open", closed || metrics.is_locked ? "bad" : "good"),
          badge(activity.label, activity.tone),
          issue.assignee_count > 0 ? badge(`Assigned (${issue.assignee_count})`, "warn") : null,
          h("span", { class: "text-xs text-slate-400", text: `Last activity ${daysAgo(metrics.last_comment_date)}` })
        ),
        countDone(issue) > 0 ? progressBlock(issue) : null, // only once you have started this one
        h("button", { type: "button", class: "btn w-full", "aria-label": `Inspect issue: ${issue.title}`, onClick: () => selectIssue(issue) }, "Inspect issue", arrowIcon())
      )
    )
  );
}

function renderIssues({ animate = true } = {}) {
  const root = $("issue-groups");
  root.setAttribute("aria-busy", "false");
  $("result-count").textContent = plural(state.issues.length, "issue");

  if (state.issues.length === 0) {
    root.replaceChildren(
      h(
        "div",
        { class: "glass rounded-2xl p-6 text-sm text-slate-400" },
        h("p", { class: "font-semibold text-slate-200", text: "No open good first issues match this search." }),
        h("p", { class: "mt-1", text: "Try fewer or different words, or clear the search box." })
      )
    );
    return;
  }

  let index = 0;
  root.replaceChildren(
    ...groupIssues(state.issues).map((group) =>
      h(
        "section",
        { class: "issue-group", "data-tier": group.key, "aria-labelledby": `group-${group.key}` },
        h(
          "div",
          { class: "group-head" },
          h("span", { class: "tier-dots", "aria-hidden": "true" }, [1, 2, 3, 4].map((n) => h("i", { class: n <= group.dots ? "on" : "" }))),
          h("div", {}, h("h3", { id: `group-${group.key}`, class: "font-display text-xl font-semibold tracking-tight text-white", text: group.title }), h("p", { class: "text-sm text-slate-400", text: `${plural(group.issues.length, "issue")}. ${group.hint}` }))
        ),
        h("ul", { class: "grid grid-cols-1 gap-6 lg:grid-cols-2 xl:grid-cols-3" }, group.issues.map((issue) => issueCard(issue, index++, animate)))
      )
    )
  );
}

function renderRecap() {
  const picked = [...state.skills.languages, ...[...state.skills.topics].map(skillLabel)];
  $("l2-sub").textContent = picked.length
    ? `Ranked by how well they match ${picked.join(", ")}. The closest matches come first, then the list fades toward less related issues.`
    : "You did not pick any skills, so these run from the easiest to the hardest.";
}

function rankAndRender({ animate = true } = {}) {
  state.issues = rankIssues(state.pool);
  renderRecap();
  renderIssues({ animate });
  renderGlobalProgress();
}

function renderSkeletons() {
  const root = $("issue-groups");
  root.setAttribute("aria-busy", "true");
  root.replaceChildren(h("ul", { class: "grid grid-cols-1 gap-6 lg:grid-cols-2 xl:grid-cols-3" }, ...[0, 1, 2].map(() => h("li", {}, h("div", { class: "skeleton h-80 w-full" })))));
}

function showIssueError(message) {
  const box = $("issue-error");
  box.replaceChildren();
  if (message) {
    box.append(
      h("p", { text: message }),
      h("button", { type: "button", class: "btn-ghost mt-3", text: "Try again", onClick: () => loadIssues() })
    );
  }
  box.classList.toggle("hidden", !message);
}

/** One GitHub round trip per search. Skills never trigger a fetch: they only re-rank what is already here. */
async function loadIssues() {
  if (listController) listController.abort();
  const controller = (listController = new AbortController());
  const token = ++listToken;
  const query = state.q.trim();

  state.loading = true;
  showIssueError("");
  $("progress-detail").textContent = "Loading issues from GitHub...";
  $("result-count").textContent = "";
  renderSkeletons();

  try {
    const issues = await fetchIssues({ language: new Set(), topic: new Set(), q: query }, controller.signal);
    if (token !== listToken) return;
    state.pool = issues;
    state.poolReady = true;
    state.poolQuery = query;
    state.loading = false;
    issues.forEach(registerIssue);
    rankAndRender();
  } catch (error) {
    if (error && error.name === "AbortError") return;
    if (token !== listToken) return;
    state.loading = false;
    state.pool = [];
    state.poolReady = false;
    state.issues = [];
    const root = $("issue-groups");
    root.setAttribute("aria-busy", "false");
    root.replaceChildren();
    $("result-count").textContent = "";
    $("progress-detail").textContent = "Progress appears here once issues load.";
    showIssueError(error.message);
    renderGlobalProgress();
  }
}

/** Entering layer 2: reuse what is already fetched (and re-rank for any new skills), or fetch for the first time. */
function ensureIssues() {
  if (state.loading) return;
  if (state.poolReady && state.poolQuery === state.q.trim()) rankAndRender();
  else loadIssues();
}

/* ====================================================================
   LAYER 3: the problem, a typical approach, and the health check
   ==================================================================== */
function renderCheck() {
  const v = state.verification;
  if (!v) return;
  const tone = { healthy: "good", caution: "warn", blocked: "bad" }[v.health_state];
  const headline = {
    healthy: "Healthy: safe to start",
    caution: "Proceed with caution",
    blocked: "Blocked: not open to contributors",
  }[v.health_state];
  const issue = v.issue;

  $("check-panel").replaceChildren(
    h(
      "div",
      { class: "swap-in space-y-5" },
      h(
        "div",
        { class: "space-y-2" },
        h("div", { class: "flex flex-wrap items-center gap-2" }, badge(headline, tone)),
        h("p", { class: "text-sm text-slate-400", text: "We checked this issue against GitHub just now, so you know it is still worth your time." })
      ),
      h(
        "div",
        {},
        h("div", { class: "mb-1.5 flex justify-between text-xs text-slate-400" }, h("span", { text: "Health score" }), h("span", { class: "tabular-nums", text: `${v.health_score} out of 100` })),
        h(
          "div",
          { class: `meter meter-${tone}`, role: "progressbar", "aria-label": "Health score", "aria-valuemin": "0", "aria-valuemax": "100", "aria-valuenow": String(v.health_score) },
          h("span", { id: "meter-fill" })
        )
      ),
      h(
        "ul",
        { class: "grid gap-3" },
        v.badges.map((item) =>
          h(
            "li",
            { class: "rounded-xl border border-slate-800/60 bg-slate-950/50 p-3" },
            badge(item.label, item.state),
            h("p", { class: "mt-2 text-sm text-slate-400", text: item.detail })
          )
        )
      ),
      h(
        "p",
        { class: "text-xs text-slate-400", text: `Last comment on ${formatDate(issue.status_metrics.last_comment_date)}. ${plural(issue.comment_count, "comment")}, ${issue.assignee_count} assigned. Checked from GitHub at ${new Date(v.checked_at).toLocaleTimeString()}.` }
      )
    )
  );

  requestAnimationFrame(() => {
    const fill = $("meter-fill");
    if (fill) fill.style.width = `${v.health_score}%`;
  });
}

function renderUnderstand(issue) {
  const rel = state.rel.get(issue.id);
  $("understand-panel").replaceChildren(
    h(
      "div",
      { class: "swap-in space-y-5" },
      h(
        "div",
        { class: "flex flex-wrap items-center justify-between gap-3" },
        languagePill(issue.programming_language),
        h("div", { class: "flex items-center gap-3" }, difficultyMeter(issue.difficulty_rating), bookmarkButton(issue))
      ),
      h("h3", { class: "font-display text-xl font-semibold leading-snug text-white", text: issue.title }),
      h("div", { class: "flex flex-wrap gap-2" }, monoLabel(`${issue.repo_owner}/${issue.repo_name}`)),
      rel && rel.percent > 0 ? matchLine(rel) : null,
      h(
        "div",
        { class: "space-y-1.5" },
        h("p", { class: "field-label", text: "The problem, as the issue describes it" }),
        h("p", { class: "max-w-prose leading-relaxed text-slate-300", text: issue.context_summary })
      ),
      issue.active_handles.length
        ? h(
            "div",
            { class: "space-y-2" },
            h("p", { class: "text-sm font-semibold text-slate-200", text: "Active on the thread" }),
            h("ul", { class: "flex flex-wrap gap-2" }, issue.active_handles.map((handle) => h("li", {}, monoLabel(`@${handle}`, "mono-handle"))))
          )
        : null,
      h(
        "div",
        { class: "grid gap-3 sm:grid-cols-2" },
        externalLink("context-link", issue.github_issue_url, "Read the issue on GitHub"),
        externalLink("context-link", issue.contributing_guidelines_url, "Contributing guidelines")
      ),
      issue.topics.length
        ? h("div", { class: "flex flex-wrap gap-1.5" }, issue.topics.map((topic) => h("span", { class: "rounded-md bg-slate-800/70 px-2 py-0.5 text-xs text-slate-300", text: topic })))
        : null
    )
  );
}

// What an issue of each kind usually asks for. Picked from the labels and title, so it is guidance, not a diagnosis.
const APPROACHES = [
  {
    test: /\b(docs?|documentation|readme|typos?|spelling)\b/i,
    kind: "Documentation change",
    summary: "You will be editing words, not code.",
    steps: ["Find the file or page that holds the text you need to change.", "Edit it directly, and keep the project's tone and formatting.", "Re-read the result, and check that any links you touched still work."],
    tip: "Docs fixes are the gentlest first pull request: small, easy to review, and quick to merge.",
  },
  {
    test: /\b(tests?|testing|flaky|coverage)\b/i,
    kind: "Tests",
    summary: "You will add or repair a test.",
    steps: ["Run the existing tests so you know what passing looks like.", "Write the smallest test that captures the behaviour in the issue.", "Make sure it fails for the right reason, then passes once the code is correct."],
    tip: "Copy the style of the tests next to yours: maintainers like consistency.",
  },
  {
    test: /\b(accessib\w*|a11y|aria|screen[- ]reader|contrast)\b/i,
    kind: "Accessibility fix",
    summary: "You will make the product easier to use for everyone.",
    steps: ["Reproduce the problem with the keyboard alone, or a screen reader if you have one.", "Find the element involved and fix its label, role, focus order or contrast.", "Check again with the keyboard, and run the project's accessibility linter if it has one."],
    tip: "A missing label or alt text is a small change that matters a lot to real users.",
  },
  {
    test: /\b(security|vulnerab\w*|cve|xss|csrf)\b/i,
    kind: "Security fix",
    summary: "Take extra care and keep it narrow.",
    steps: ["Read the issue carefully, and keep exploit details out of public comments if the report asks for privacy.", "Find the code that handles the input or permission in question.", "Fix it narrowly, and add a test that proves the bad case is now rejected."],
    tip: "If this looks like a serious vulnerability, check the repository's SECURITY.md first.",
  },
  {
    test: /\b(perf\w*|slow|speed|latency|memory)\b/i,
    kind: "Performance improvement",
    summary: "Measure, change one thing, measure again.",
    steps: ["Reproduce the slow case and write down the numbers.", "Find the hot spot, and change one thing at a time.", "Measure again, and put the before and after numbers in your pull request."],
    tip: "Maintainers trust numbers more than guesses.",
  },
  {
    test: /\b(refactor\w*|clean ?up|tech[- ]debt|simplif\w*)\b/i,
    kind: "Code clean-up",
    summary: "The behaviour must stay exactly the same.",
    steps: ["Run the tests first: a refactor must not change what the code does.", "Make the change in small steps, running the tests after each one.", "Keep the pull request about the clean-up only, with no new features mixed in."],
    tip: "Small, well-scoped clean-ups get reviewed the fastest.",
  },
  {
    test: /\b(typing|type hints?|mypy|annotations?)\b/i,
    kind: "Type annotations",
    summary: "You will describe the code's shapes more precisely.",
    steps: ["Find the functions or values the issue names.", "Add precise types, and avoid loose catch-alls where you can.", "Run the project's type checker and fix what it reports."],
    tip: "Run the type checker before and after, so you can show you added no new errors.",
  },
  {
    test: /\b(bugs?|fix(?:es)?|crash(?:es)?|errors?|broken|regression|fails?|incorrect)\b/i,
    kind: "Bug fix",
    summary: "Make it fail, find why, then make it work.",
    steps: ["Reproduce the problem first, so you can watch it fail.", "Trace it to the code responsible. The files named in the issue are a good start.", "Fix the smallest thing that makes it work, and add a test that would have caught it."],
    tip: "If you cannot reproduce it, say so in the thread. That is useful information too.",
  },
  {
    test: /\b(enhancement|features?|add|adds|support|implement\w*|introduce)\b/i,
    kind: "Feature or improvement",
    summary: "Agree on the goal before you build.",
    steps: ["Read the whole discussion to see exactly what the maintainers want.", "Comment with your plan before writing much code, because scope can change.", "Build the smallest working version with tests, and open the pull request early."],
    tip: "Asking a question in the thread is normal, and welcome.",
  },
];
const GENERAL_APPROACH = {
  kind: "General contribution",
  summary: "Understand it first, then keep the change small.",
  steps: ["Read the issue and its comments until you can say the problem in one sentence.", "Ask in the thread if anything is unclear, and say you would like to take it.", "Make the smallest change that resolves it, with a test where it makes sense."],
  tip: "Maintainers would rather you ask a question than build the wrong thing.",
};

const approachFor = (issue) => APPROACHES.find((a) => a.test.test(`${issue.topics.join(" ")} ${issue.title}`)) || GENERAL_APPROACH;

function renderApproach(issue) {
  const panel = $("approach-panel");
  if (!issue) {
    panel.replaceChildren(loadingBlock(3));
    return;
  }
  const approach = approachFor(issue);
  const paths = issue.affected_paths || [];
  panel.replaceChildren(
    h(
      "div",
      { class: "swap-in space-y-4" },
      h("div", { class: "flex flex-wrap items-center gap-2" }, h("h3", { class: "font-display text-lg font-semibold text-white", text: "How to approach it" }), badge(approach.kind, "info")),
      h("p", { class: "text-sm text-slate-400", text: `${approach.summary} This is a typical approach for this kind of issue, chosen from its labels and title. The maintainers' own advice in the thread always comes first.` }),
      h("ol", { class: "approach-list" }, approach.steps.map((step) => h("li", {}, step))),
      h(
        "div",
        { class: "rounded-xl border border-slate-800/60 bg-slate-950/50 p-3" },
        h("p", { class: "text-sm font-semibold text-slate-200", text: "Where to look" }),
        paths.length
          ? h("ul", { class: "mt-2 flex flex-wrap gap-2" }, paths.map((path) => h("li", {}, monoLabel(path, "inline-block text-slate-300"))))
          : h("p", { class: "mt-1 text-sm text-slate-400", text: "The issue does not name any files. Search the repository for words from the title, or ask in the thread where the change belongs." })
      ),
      h("p", { class: "text-sm text-slate-300", text: `Tip: ${approach.tip}` })
    )
  );
}

/* ====================================================================
   LAYER 4: step by step
   ==================================================================== */
function renderPlan() {
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
        h("div", { class: "min-w-0 space-y-2" }, h("h3", { class: "font-display text-xl font-semibold leading-snug text-white", text: plan.title }), monoLabel(plan.repo_full_name)),
        h("div", { class: "w-full sm:w-64" }, progressBlock(issue))
      ),
      blocked
        ? h("p", { class: "rounded-xl border border-rose-500/40 bg-rose-500/10 p-3 text-sm text-rose-200", role: "note", text: "This issue is blocked: it is locked, closed or in an archived repository. Read the plan, but check the thread before you start coding." })
        : null,
      h("ol", { class: "plan-steps", "aria-label": "Steps to resolve this issue" }, plan.actionable_checklist.map((step) => stepRow(issue.id, step, "plan"))),
      h(
        "div",
        { id: "plan-complete", class: "plan-complete space-y-3", hidden: true },
        h("h3", { id: "plan-complete-title", tabindex: "-1", class: "font-display text-xl font-semibold text-white", text: "All steps done. Nice work!" }),
        h("p", { class: "text-sm text-slate-300", text: "Once your pull request is open, the maintainers will review it. They may ask for changes. That is normal, and part of the process." }),
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
function markCurrentStep() {
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
function focusCurrentStep() {
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

/* ====================================================================
   Selection flow: Inspect issue -> layer 3, then layer 4 when the plan is ready
   ==================================================================== */
function loadingBlock(lines = 3) {
  return h("div", { class: "space-y-3", "aria-busy": "true" }, ...Array.from({ length: lines }, (_, i) => h("div", { class: "skeleton h-6", style: `width:${100 - i * 14}%` })));
}

const errorBlock = (prefix, message) =>
  h("p", { class: "rounded-xl border border-rose-500/40 bg-rose-500/10 p-3 text-sm text-rose-200", role: "alert", text: `${prefix} ${message}` });

function markSelected() {
  document.querySelectorAll("#issue-groups [data-issue-id]").forEach((card) => card.setAttribute("aria-current", String(card.dataset.issueId === state.selectedId)));
}

function setStepsReady(ready) {
  $("to-steps").setAttribute("aria-disabled", String(!ready));
  $("to-steps-label").textContent = ready ? "Show me the steps" : "Preparing your steps...";
}

/** The plan an issue card already carries: the same checklist /api/plan returns, with no extra GitHub call. */
const planFromCard = (issue) => ({
  issue_id: issue.id,
  title: issue.title,
  repo_full_name: `${issue.repo_owner}/${issue.repo_name}`,
  github_issue_url: issue.github_issue_url,
  contributing_guidelines_url: issue.contributing_guidelines_url,
  context_summary: issue.context_summary,
  actionable_checklist: issue.actionable_checklist,
});

/** `issue` may be a full card or just a bookmark record; the live check below fills in the rest. */
async function selectIssue(issue) {
  const token = ++selectionToken;
  state.selectedId = issue.id;
  state.verification = null;
  state.plan = null;
  markSelected();

  // A full card already holds its checklist, so the steps are ready at once and survive a GitHub rate limit.
  // A bookmark is only a stub, so its plan is fetched.
  const hasPlan = Array.isArray(issue.actionable_checklist) && issue.actionable_checklist.length > 0;

  if (issue.context_summary) renderUnderstand(issue);
  else $("understand-panel").replaceChildren(loadingBlock(4));
  renderApproach(issue.context_summary ? issue : null);
  $("check-panel").replaceChildren(loadingBlock());
  if (hasPlan) {
    registerIssue(issue);
    state.plan = planFromCard(issue);
    renderPlan();
  } else {
    $("start-panel").replaceChildren(loadingBlock(5));
  }
  setStepsReady(hasPlan);
  goLayer(3);

  const [verifyResult, planResult] = await Promise.allSettled([
    postJson("/api/verify", issue.github_issue_url),
    hasPlan ? Promise.resolve(null) : postJson("/api/plan", issue.github_issue_url),
  ]);
  if (token !== selectionToken) return; // a newer selection superseded this one

  if (verifyResult.status === "fulfilled") {
    state.verification = verifyResult.value;
    registerIssue(state.verification.issue);
    renderUnderstand(state.verification.issue); // the live check has the freshest details
    renderApproach(state.verification.issue);
    renderCheck();
    // The plan panel shows a warning for blocked issues; refresh it only if there is one to show.
    if (hasPlan && state.verification.health_state === "blocked") renderPlan();
  } else {
    $("check-panel").replaceChildren(errorBlock("Could not check this issue.", verifyResult.reason.message));
    if (!issue.context_summary) {
      $("understand-panel").replaceChildren(errorBlock("Could not load this issue.", verifyResult.reason.message));
      $("approach-panel").replaceChildren();
    }
  }

  if (!hasPlan) {
    if (planResult.status === "fulfilled") {
      state.plan = planResult.value;
      renderPlan();
    } else {
      $("start-panel").replaceChildren(errorBlock("Could not build a plan.", planResult.reason.message));
    }
  }
  setStepsReady(true); // on failure layer 4 shows the error, with a way back
}

/* ====================================================================
   Init
   ==================================================================== */
function onStorage(event) {
  if (!event.key || !event.key.startsWith(PROGRESS_PREFIX)) return;
  const issueId = event.key.slice(PROGRESS_PREFIX.length);
  if (!state.byId.has(issueId)) return;
  state.progress.set(issueId, loadProgress(issueId));
  syncIssue(issueId);
}

function onHistory() {
  const match = /^#step-(\d)$/.exec(location.hash);
  if (location.hash === "#bookmarks") {
    setView("bookmarks");
    return;
  }
  // In-page anchors (#team, #contact, #top, #how...) are not a move between layers: leave the user where they are.
  if (!match && location.hash !== "") return;
  setView("workspace", { scroll: false });
  goLayer(match ? Number(match[1]) : 1, { push: false });
}

/* ====================================================================
   Footer: team photos and contact
   ==================================================================== */
/** A tile shows its photo if the file exists, otherwise the initials already in the markup. */
function initPeople() {
  document.querySelectorAll(".photo-slot[data-photo]").forEach((slot) => {
    const img = slot.querySelector("img");
    const fallback = slot.querySelector(".photo-fallback");
    const probe = new Image();
    probe.onload = () => {
      img.src = probe.src;
      img.hidden = false;
      if (fallback) fallback.hidden = true;
      slot.classList.add("has-photo");
    };
    probe.src = slot.dataset.photo; // a missing file just leaves the initials in place
  });
}

async function copyEmail(event) {
  const button = event.currentTarget;
  try {
    await navigator.clipboard.writeText(button.dataset.copy);
    showToast("Email address copied");
    button.textContent = "Copied";
    setTimeout(() => { button.textContent = "Copy"; }, 1800);
  } catch {
    showToast("Could not copy automatically. The address is shown next to the button.", "error");
  }
}

async function init() {
  state.skills = loadSkills();

  $("search-input").addEventListener("input", (event) => {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(() => {
      state.q = event.target.value;
      loadIssues();
    }, SEARCH_DEBOUNCE_MS);
  });

  // Layer navigation
  document.querySelectorAll("#stepper button[data-layer]").forEach((button) =>
    button.addEventListener("click", () => {
      const n = Number(button.dataset.layer);
      if (!canEnter(n)) showToast("Choose an issue first: press Inspect issue on a card.");
      else goLayer(n);
    })
  );
  $("continue-skills").addEventListener("click", () => goLayer(2));
  $("clear-skills").addEventListener("click", clearSkills);
  $("change-skills").addEventListener("click", () => goLayer(1));
  $("back-to-skills").addEventListener("click", () => goLayer(1));
  $("back-to-issues").addEventListener("click", () => goLayer(2));
  $("back-to-problem").addEventListener("click", () => goLayer(3));
  $("pick-another").addEventListener("click", () => goLayer(2));
  $("to-steps").addEventListener("click", () => {
    if ($("to-steps").getAttribute("aria-disabled") !== "true") goLayer(4);
  });
  $("home-link").addEventListener("click", (event) => {
    event.preventDefault();
    setView("workspace", { scroll: false });
    goLayer(1);
  });

  // Layer 1 hero buttons scroll to the part they name
  $("hero-cta").addEventListener("click", () => {
    const form = $("skills-form");
    form.scrollIntoView({ behavior: motion(), block: "start" });
    const first = form.querySelector("input");
    if (first) first.focus({ preventScroll: true });
  });
  $("hero-how").addEventListener("click", () => $("how").scrollIntoView({ behavior: motion(), block: "start" }));

  // Footer
  initPeople();
  $("copy-email").addEventListener("click", copyEmail);

  // Bookmarks
  $("view-workspace").addEventListener("click", () => setView("workspace"));
  $("view-bookmarks").addEventListener("click", () => setView("bookmarks"));
  $("back-to-workspace").addEventListener("click", () => setView("workspace"));

  window.addEventListener("storage", onStorage);
  window.addEventListener("popstate", onHistory);

  renderGlobalProgress();
  renderSkillSummary();
  paintStepper();
  setStepsReady(false);

  // Bookmarks are a quick local call; GitHub is only contacted when layer 2 opens.
  const bookmarksReady = loadBookmarks();
  try {
    const facets = await api("/api/facets");
    state.facets.languages = facets.languages;
    state.facets.topics = facets.topics;
    // Forget saved skills the server no longer offers.
    state.skills.languages = new Set([...state.skills.languages].filter((name) => facets.languages.includes(name)));
    state.skills.topics = new Set([...state.skills.topics].filter((name) => facets.topics.includes(name)));
    renderSkills();
    if (!facets.github_authenticated) {
      const note = $("auth-note");
      note.textContent = "GitHub allows 10 searches a minute without a token. Add GITHUB_TOKEN to .env to raise that to 30, and the hourly limit on issue checks from 60 to 5,000.";
      note.classList.remove("hidden");
    }
  } catch (error) {
    const box = $("skills-error");
    box.textContent = `Could not load the skills list. ${error.message} You can still continue without picking skills.`;
    box.classList.remove("hidden");
  }
  await bookmarksReady;

  // Deep links: #bookmarks opens that view, #step-2 opens the issues. Layers 3 and 4 need a chosen issue, so they fall back to 2.
  if (location.hash === "#bookmarks") setView("bookmarks");
  else {
    const match = /^#step-(\d)$/.exec(location.hash);
    if (match && Number(match[1]) > 1) goLayer(Number(match[1]), { push: false, focus: false });
  }
}

document.addEventListener("DOMContentLoaded", init);
