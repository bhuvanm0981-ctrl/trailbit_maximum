import { fetchIssues } from "./api.js";
import { bookmarkButton } from "./bookmarks.js";
import { h, showToast } from "./dom.js";
import { arrowIcon } from "./layers.js";
import { countDone, registerIssue, renderGlobalProgress } from "./progress.js";
import { selectIssue } from "./select.js";
import { skillCount, skillLabel, topicRegex } from "./skills.js";
import { $, state } from "./state.js";
import { progressBlock } from "./steps.js";
import { ACTIVITY, badge, daysAgo, difficultyMeter, languagePill, monoLabel, plural, shortPath } from "./ui.js";

export let listController = null;

export let listToken = 0;

/* ====================================================================
   LAYER 2: rank by relatedness, then render in groups that fade toward "less related"
   ==================================================================== */
/** How well one issue matches the picked skills: a language match is worth 3, each matched area 2 (up to two). */
export function relatedness(issue) {
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

export const TIERS = [
  { key: "best", title: "Best matches", hint: "Closest to the skills you picked.", dots: 4 },
  { key: "good", title: "Good matches", hint: "They match a good part of what you picked.", dots: 3 },
  { key: "partial", title: "Partial matches", hint: "A smaller overlap with your skills.", dots: 2 },
  { key: "stretch", title: "Outside your skills", hint: "A stretch, but still marked as beginner friendly.", dots: 1 },
];

/** Highest match first; ties go to the easier issue, then to the order GitHub returned. */
export function rankIssues(list) {
  state.rel = new Map(list.map((issue) => [issue.id, relatedness(issue)]));
  const percent = (issue) => (state.rel.get(issue.id) ? state.rel.get(issue.id).percent : 0);
  return list
    .map((issue, index) => ({ issue, index }))
    .sort((a, b) => percent(b.issue) - percent(a.issue) || a.issue.difficulty_rating - b.issue.difficulty_rating || a.index - b.index)
    .map((entry) => entry.issue);
}

export function groupIssues(ranked) {
  if (!skillCount()) {
    return [{ key: "easy", title: "Easiest to start with", hint: "You did not pick skills, so these run from the easiest to the hardest.", dots: 4, issues: ranked }];
  }
  return TIERS.map((tier) => ({ ...tier, issues: ranked.filter((issue) => state.rel.get(issue.id).tier === tier.key) })).filter((group) => group.issues.length);
}

export function matchLine(rel) {
  const names = [rel.matchedLang, ...rel.matchedTopics.map(skillLabel)].filter(Boolean);
  return h(
    "div",
    { class: "flex flex-wrap items-center gap-x-3 gap-y-1.5" },
    h("span", { class: `match-pill match-${rel.tier}` }, h("span", { class: "match-bar", "aria-hidden": "true" }, h("i", { style: `width:${rel.percent}%` })), `${rel.percent}% match`),
    names.length ? h("span", { class: "text-xs text-ink-body", text: `Matches: ${names.join(", ")}` }) : null
  );
}

export function issueCard(issue, index, animate) {
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
        class: `issue-card ${animate ? "enter" : ""} group flex h-full flex-col gap-4 rounded-2xl border border-line/40 p-5 transition duration-300 hover:-translate-y-1.5 hover:border-teal/60 hover:shadow-[0_14px_30px_rgba(1,70,74,0.18)]`,
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
      h("h4", { id: titleId, class: "font-display text-lg font-semibold leading-snug text-ink", text: issue.title }),
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
            issue.affected_paths.slice(0, 2).map((path) => h("li", {}, monoLabel(shortPath(path), "inline-block text-ink-muted", path)))
          )
        : null,
      issue.topics.length
        ? h("div", { class: "flex flex-wrap gap-1.5" }, issue.topics.map((topic) => h("span", { class: "rounded-md bg-line/15 px-2 py-0.5 text-xs text-ink-body", text: topic })))
        : null,
      h(
        "div",
        { class: "mt-auto space-y-4" },
        h(
          "div",
          { class: "flex flex-wrap items-center gap-2 border-t border-line/35 pt-4" },
          badge(closed ? "Closed" : metrics.is_locked ? "Locked" : "Open", closed || metrics.is_locked ? "bad" : "good"),
          badge(activity.label, activity.tone),
          issue.assignee_count > 0 ? badge(`Assigned (${issue.assignee_count})`, "warn") : null,
          h("span", { class: "text-xs text-ink-muted", text: `${issue.opened_date ? `Opened ${daysAgo(issue.opened_date)}, ` : ""}last activity ${daysAgo(metrics.last_comment_date)}` })
        ),
        countDone(issue) > 0 ? progressBlock(issue) : null, // only once you have started this one
        h("button", { type: "button", class: "btn w-full", "aria-label": `Inspect issue: ${issue.title}`, onClick: () => selectIssue(issue) }, "Inspect issue", arrowIcon())
      )
    )
  );
}

export function renderIssues({ animate = true } = {}) {
  const root = $("issue-groups");
  root.setAttribute("aria-busy", "false");
  $("result-count").textContent = plural(state.issues.length, "issue");

  if (state.issues.length === 0) {
    root.replaceChildren(
      h(
        "div",
        { class: "glass rounded-2xl p-6 text-sm text-ink-muted" },
        h("p", { class: "font-semibold text-ink", text: "No open good first issues match this search." }),
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
          h("div", {}, h("h3", { id: `group-${group.key}`, class: "font-display text-xl font-semibold tracking-tight text-ink", text: group.title }), h("p", { class: "text-sm text-ink-muted", text: `${plural(group.issues.length, "issue")}. ${group.hint}` }))
        ),
        h("ul", { class: "grid grid-cols-1 gap-6 lg:grid-cols-2 xl:grid-cols-3" }, group.issues.map((issue) => issueCard(issue, index++, animate)))
      )
    )
  );
}

export function renderRecap() {
  const picked = [...state.skills.languages, ...[...state.skills.topics].map(skillLabel)];
  $("l2-sub").textContent = picked.length
    ? `Ranked by how well they match ${picked.join(", ")}. The closest matches come first, then the list fades toward less related issues.`
    : "You did not pick any skills, so these run from the easiest to the hardest.";
}

export function rankAndRender({ animate = true } = {}) {
  state.issues = rankIssues(state.pool);
  renderRecap();
  renderIssues({ animate });
  renderGlobalProgress();
  paintLoadMore();
}

/** The "Load more" button shows only while GitHub has another page for this search. */
export function paintLoadMore() {
  const button = $("load-more");
  if (!button) return;
  button.hidden = !(state.hasMore && state.poolReady && !state.loading);
  button.disabled = state.loadingMore;
  button.textContent = state.loadingMore ? "Loading more issues..." : "Load more issues";
}

/** What the current search is, so a changed search or order is told apart from re-entering the layer. */
const searchKey = () => `${state.q.trim().length >= 2 ? state.q.trim() : ""}|${state.sort}`;

/** The next page of the same search, added to the pool and ranked together with it. */
export async function loadMore() {
  if (state.loadingMore || state.loading || !state.hasMore) return;
  const token = listToken;
  state.loadingMore = true;
  paintLoadMore();
  try {
    const { issues, hasMore } = await fetchIssues({ q: state.q, sort: state.sort, page: state.page + 1 });
    if (token !== listToken) return; // a new search started meanwhile
    const known = new Set(state.pool.map((issue) => issue.id));
    const fresh = issues.filter((issue) => !known.has(issue.id));
    fresh.forEach(registerIssue);
    state.pool = state.pool.concat(fresh);
    state.page += 1;
    state.hasMore = hasMore;
    rankAndRender({ animate: false });
  } catch (error) {
    showToast(`Could not load more issues. ${error.message}`, "error");
  } finally {
    state.loadingMore = false;
    paintLoadMore();
  }
}

export function renderSkeletons() {
  const root = $("issue-groups");
  root.setAttribute("aria-busy", "true");
  root.replaceChildren(h("ul", { class: "grid grid-cols-1 gap-6 lg:grid-cols-2 xl:grid-cols-3" }, ...[0, 1, 2].map(() => h("li", {}, h("div", { class: "skeleton h-80 w-full" })))));
}

export function showIssueError(message) {
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
export async function loadIssues() {
  if (listController) listController.abort();
  const controller = (listController = new AbortController());
  const token = ++listToken;
  const key = searchKey();

  state.loading = true;
  state.hasMore = false;
  paintLoadMore();
  showIssueError("");
  $("progress-detail").textContent = "Loading issues from GitHub...";
  $("result-count").textContent = "";
  renderSkeletons();

  try {
    const { issues, hasMore } = await fetchIssues({ q: state.q, sort: state.sort, page: 1 }, controller.signal);
    if (token !== listToken) return;
    state.pool = issues;
    state.page = 1;
    state.hasMore = hasMore;
    state.poolReady = true;
    state.poolQuery = key;
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
    state.hasMore = false;
    paintLoadMore();
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
export function ensureIssues() {
  if (state.loading) return;
  if (state.poolReady && state.poolQuery === searchKey()) rankAndRender();
  else loadIssues();
}
