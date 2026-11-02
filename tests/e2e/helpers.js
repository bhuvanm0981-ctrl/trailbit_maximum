const { expect } = require("@playwright/test");

const TITLE = "Fix timezone parsing in the ICS importer"; // acme/pyparse#11 in tests/fakes.py
const CARD = '#issue-groups article[data-issue-id="1001"]';

/** Switches on the test server (see tests/e2e/server.py). */
const control = (request, path, params = {}) => request.get(`/__test/${path}?${new URLSearchParams(params)}`);

/** Collects everything that should never happen: script errors, console errors (CSP violations are console errors), bad responses, requests to other sites and dialogs. */
function watch(page, { allowFailedRequests = false } = {}) {
  const problems = [];
  const foreign = [];
  const requests = [];
  const dialogs = [];
  page.on("console", (message) => {
    if (message.type() !== "error") return;
    if (allowFailedRequests && /Failed to load resource/.test(message.text())) return;
    problems.push(`console: ${message.text()}`);
  });
  page.on("pageerror", (error) => problems.push(`pageerror: ${error.message}`));
  page.on("response", (response) => {
    if (response.status() >= 400 && !allowFailedRequests) problems.push(`HTTP ${response.status()} ${response.url()}`);
  });
  page.on("request", (request) => {
    const url = new URL(request.url());
    requests.push({ url: request.url(), method: request.method(), body: request.postData() });
    if (url.protocol.startsWith("http") && url.hostname !== "127.0.0.1") foreign.push(request.url());
  });
  page.on("dialog", (dialog) => {
    dialogs.push(dialog.message());
    dialog.dismiss();
  });
  return { problems, foreign, requests, dialogs };
}

const cards = (page) => page.locator("#issue-groups article[data-issue-id]");

async function openIssues(page, skills = []) {
  await page.goto("/");
  for (const skill of skills) await page.locator(`label[for="skill-languages-${skill}"]`).click();
  await page.locator("#continue-skills").click();
  await expect(page.locator("#layer-2")).toBeVisible();
  await expect(cards(page).first()).toBeVisible();
}

/** Horizontal overflow in pixels (0 means the page fits its width). */
const overflow = (page) => page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);

module.exports = { TITLE, CARD, control, watch, cards, openIssues, overflow };
