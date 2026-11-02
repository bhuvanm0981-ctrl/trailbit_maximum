/* Trailbit frontend entry point: wires every module together once the page has loaded. */
import { api } from "./api.js";
import { loadBookmarks, setView } from "./bookmarks.js";
import { showToast } from "./dom.js";
import { copyEmail, initPeople } from "./footer.js";
import { loadIssues, loadMore } from "./issues.js";
import { canEnter, goLayer, motion, paintStepper } from "./layers.js";
import { loadAllProgress, loadProgress, renderGlobalProgress, syncIssue } from "./progress.js";
import { setStepsReady } from "./select.js";
import { clearSkills, loadSkills, renderSkillSummary, renderSkills } from "./skills.js";
import { $, PROGRESS_PREFIX, SEARCH_DEBOUNCE_MS, state } from "./state.js";

export let searchTimer = null;

/* ====================================================================
   Init
   ==================================================================== */
export function onStorage(event) {
  if (!event.key || !event.key.startsWith(PROGRESS_PREFIX)) return;
  const issueId = event.key.slice(PROGRESS_PREFIX.length);
  if (!state.byId.has(issueId)) return;
  state.progress.set(issueId, loadProgress(issueId));
  syncIssue(issueId);
}

export function onHistory() {
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
export async function init() {
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
  $("skills-form").addEventListener("submit", (event) => event.preventDefault()); // the form only collects skills
  $("sort-select").addEventListener("change", (event) => {
    state.sort = event.target.value;
    loadIssues();
  });
  $("load-more").addEventListener("click", loadMore);
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

  loadAllProgress();
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
    state.checklistLength = facets.checklist_length || state.checklistLength;
    // Forget saved skills the server no longer offers.
    state.skills.languages = new Set([...state.skills.languages].filter((name) => facets.languages.includes(name)));
    state.skills.topics = new Set([...state.skills.topics].filter((name) => facets.topics.includes(name)));
    renderSkills();
    if (facets.show_token_hint) {  // developers only: the server never sets this in production
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

