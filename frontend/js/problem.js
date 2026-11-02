import { bookmarkButton } from "./bookmarks.js";
import { externalLink, h } from "./dom.js";
import { matchLine } from "./issues.js";
import { loadingBlock } from "./select.js";
import { $, state } from "./state.js";
import { badge, difficultyMeter, formatDate, languagePill, monoLabel, plural } from "./ui.js";

/* ====================================================================
   LAYER 3: the problem, a typical approach, and the health check
   ==================================================================== */
export function renderCheck() {
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
        h("p", { class: "text-sm text-ink-muted", text: "We checked this issue against GitHub just now, so you know it is still worth your time." })
      ),
      h(
        "div",
        {},
        h("div", { class: "mb-1.5 flex justify-between text-xs text-ink-muted" }, h("span", { text: "Health score" }), h("span", { class: "tabular-nums", text: `${v.health_score} out of 100` })),
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
            { class: "rounded-xl border border-line/35 bg-white/50 p-3" },
            badge(item.label, item.state),
            h("p", { class: "mt-2 text-sm text-ink-muted", text: item.detail })
          )
        )
      ),
      h(
        "p",
        { class: "text-xs text-ink-muted", text: `Last comment on ${formatDate(issue.status_metrics.last_comment_date)}. ${plural(issue.comment_count, "comment")}, ${issue.assignee_count} assigned. Checked from GitHub at ${new Date(v.checked_at).toLocaleTimeString()}.` }
      )
    )
  );

  requestAnimationFrame(() => {
    const fill = $("meter-fill");
    if (fill) fill.style.width = `${v.health_score}%`;
  });
}

export function renderUnderstand(issue) {
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
      h("h3", { class: "font-display text-xl font-semibold leading-snug text-ink", text: issue.title }),
      h("div", { class: "flex flex-wrap gap-2" }, monoLabel(`${issue.repo_owner}/${issue.repo_name}`)),
      rel && rel.percent > 0 ? matchLine(rel) : null,
      h(
        "div",
        { class: "space-y-1.5" },
        h("p", { class: "field-label", text: "The problem, as the issue describes it" }),
        h("p", { class: "max-w-prose leading-relaxed text-ink-body", text: issue.context_summary })
      ),
      issue.active_handles.length
        ? h(
            "div",
            { class: "space-y-2" },
            h("p", { class: "text-sm font-semibold text-ink", text: "Active on the thread" }),
            h("ul", { class: "flex flex-wrap gap-2" }, issue.active_handles.map((handle) => h("li", {}, monoLabel(`@${handle}`, "mono-handle"))))
          )
        : null,
      h(
        "div",
        { class: "grid gap-3 sm:grid-cols-2" },
        externalLink("context-link", issue.github_issue_url, "Read the issue on GitHub"),
        externalLink("context-link", issue.contributing_guidelines_url, "Contributing guidelines")
      ),
      issue.linked_prs && issue.linked_prs.length
        ? h(
            "div",
            { class: "space-y-2" },
            h("p", { class: "text-sm font-semibold text-ink", text: "Open pull requests that mention this issue" }),
            h("ul", { class: "space-y-1 text-sm" }, issue.linked_prs.map((url) => h("li", {}, externalLink("text-link", url, url.replace("https://github.com/", "")))))
          )
        : null,
      h("div", { id: "guide-slot" }), // filled by renderGuide() once /api/guide answers
      issue.topics.length
        ? h("div", { class: "flex flex-wrap gap-1.5" }, issue.topics.map((topic) => h("span", { class: "rounded-md bg-line/15 px-2 py-0.5 text-xs text-ink-body", text: topic })))
        : null
    )
  );
}

// What an issue of each kind usually asks for. Picked from the labels and title, so it is guidance, not a diagnosis.
export const APPROACHES = [
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
export const GENERAL_APPROACH = {
  kind: "General contribution",
  summary: "Understand it first, then keep the change small.",
  steps: ["Read the issue and its comments until you can say the problem in one sentence.", "Ask in the thread if anything is unclear, and say you would like to take it.", "Make the smallest change that resolves it, with a test where it makes sense."],
  tip: "Maintainers would rather you ask a question than build the wrong thing.",
};

export const approachFor = (issue) => APPROACHES.find((a) => a.test.test(`${issue.topics.join(" ")} ${issue.title}`)) || GENERAL_APPROACH;

export function renderApproach(issue) {
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
      h("div", { class: "flex flex-wrap items-center gap-2" }, h("h3", { class: "font-display text-lg font-semibold text-ink", text: "How to approach it" }), badge(approach.kind, "info")),
      h("p", { class: "text-sm text-ink-muted", text: `${approach.summary} This is a typical approach for this kind of issue, chosen from its labels and title. The maintainers' own advice in the thread always comes first.` }),
      h("ol", { class: "approach-list" }, approach.steps.map((step) => h("li", {}, step))),
      h(
        "div",
        { class: "rounded-xl border border-line/35 bg-white/50 p-3" },
        h("p", { class: "text-sm font-semibold text-ink", text: "Where to look" }),
        paths.length
          ? h("ul", { class: "mt-2 flex flex-wrap gap-2" }, paths.map((path) => h("li", {}, monoLabel(path, "inline-block text-ink-body"))))
          : h("p", { class: "mt-1 text-sm text-ink-muted", text: "The issue does not name any files. Search the repository for words from the title, or ask in the thread where the change belongs." })
      ),
      h("p", { class: "text-sm text-ink-body", text: `Tip: ${approach.tip}` })
    )
  );
}

/** The repository's own rules, quoted from its CONTRIBUTING guide. They arrive after the rest of the page, so they get their own slot. */
export function renderGuide(rules) {
  const slot = $("guide-slot");
  if (!slot) return;
  if (!rules || !rules.length) {
    slot.replaceChildren();
    return;
  }
  slot.replaceChildren(
    h(
      "div",
      { class: "swap-in space-y-2" },
      h("p", { class: "text-sm font-semibold text-ink", text: "From the contributing guide" }),
      h("ul", { class: "list-disc space-y-1 pl-5 text-sm leading-relaxed text-ink-body" }, rules.map((rule) => h("li", { text: rule })))
    )
  );
}
