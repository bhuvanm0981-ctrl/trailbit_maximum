import { api } from "./api.js";
import { externalLink, h, showToast, starIcon } from "./dom.js";
import { selectIssue } from "./select.js";
import { $, LEAVE_ANIMATION_MS, sleep, state } from "./state.js";
import { formatDate, languagePill, monoLabel, plural } from "./ui.js";

/* ====================================================================
   Bookmarks
   ==================================================================== */
/** `beforeToggle` may return a promise; the toggle waits for it (used to fade a card out first). */
export function bookmarkButton(issue, { beforeToggle = null } = {}) {
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

export function paintBookmark(button, saved, animate) {
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
export function syncBookmarks({ animate = false } = {}) {
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

export async function toggleBookmark(issue) {
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
      const saved = await api("/api/bookmarks", { method: "POST", body: JSON.stringify({ github_url: issue.github_issue_url }) });
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

export async function loadBookmarks() {
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

export function bookmarkCard(bookmark) {
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
        class: "issue-card enter group flex h-full flex-col gap-4 rounded-2xl border border-line/40 p-5 transition duration-300 hover:-translate-y-1.5 hover:border-teal/60 hover:shadow-[0_14px_30px_rgba(1,70,74,0.18)]",
        "data-bookmark-card": bookmark.id,
      },
      h("div", { class: "flex items-center justify-between gap-3" }, languagePill(bookmark.programming_language), star),
      h("h3", { class: "font-display text-lg font-semibold leading-snug text-ink", text: bookmark.title }),
      h("div", { class: "flex flex-wrap gap-2" }, monoLabel(`${bookmark.repo_owner}/${bookmark.repo_name}`)),
      h("p", { class: "text-xs text-ink-muted", text: `Saved ${formatDate(bookmark.bookmarked_at)}` }),
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

export function renderBookmarksView() {
  const saved = [...state.bookmarks.values()].sort((a, b) => String(b.bookmarked_at).localeCompare(String(a.bookmarked_at)));
  $("bookmarks-subtitle").textContent = saved.length ? `${plural(saved.length, "saved issue")}, newest first.` : "Nothing saved yet.";
  const grid = $("bookmark-grid");
  if (!saved.length) {
    grid.replaceChildren(
      h(
        "li",
        { class: "glass col-span-full rounded-2xl p-8 text-center" },
        h("p", { class: "font-display text-lg font-semibold text-ink", text: "No bookmarks yet" }),
        h("p", { class: "mx-auto mt-1 max-w-md text-sm text-ink-muted", text: "Choose the star on any issue to keep it here, even after you close this page." }),
        h("button", { type: "button", class: "btn mt-4", text: "Browse issues", onClick: () => setView("workspace") })
      )
    );
    return;
  }
  grid.replaceChildren(...saved.map(bookmarkCard));
}

export function inspectBookmark(bookmark) {
  setView("workspace");
  selectIssue(bookmark);
}

/** `scroll: false` is for callers whose own action already scrolls (nav anchors), so the two do not fight. */
export function setView(view, { scroll = true } = {}) {
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
