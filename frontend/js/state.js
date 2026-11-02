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
export const API_BASE = window.location.protocol === "file:" ? "http://127.0.0.1:8000" : "";
export const PROGRESS_PREFIX = "trailbit:progress:";
export const SKILLS_KEY = "trailbit:skills";
export const SEARCH_DEBOUNCE_MS = 350;
export const LEAVE_ANIMATION_MS = 220;
export const TOAST_MS = 3200;
export const SVG_NS = "http://www.w3.org/2000/svg";
export const STAR_PATH = "M12 3.5l2.6 5.3 5.9.9-4.3 4.1 1 5.8L12 16.9 6.8 19.6l1-5.8L3.5 9.7l5.9-.9L12 3.5z";

export const state = {
  layer: 1,               // which of the four layers is showing
  skills: { languages: new Set(), topics: new Set() },
  q: "",                  // free-text search on layer 2
  sort: "updated",        // how GitHub orders the search: updated, newest, discussed or quiet
  page: 1,                // the last page of results fetched
  hasMore: false,         // whether GitHub has another page for this search
  loadingMore: false,
  checklistLength: 8,     // steps in every checklist; the server confirms it with /api/facets
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

export const $ = (id) => document.getElementById(id);
export const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
