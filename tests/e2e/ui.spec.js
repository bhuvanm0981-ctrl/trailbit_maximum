const { test, expect } = require("@playwright/test");
const axeSource = require("axe-core").source;
const { TITLE, CARD, control, watch, cards, openIssues } = require("./helpers");

test.beforeEach(async ({ request }) => { await control(request, "reset"); });

test("the page uses only this site's files, its own fonts, and raises no errors under the security policy", async ({ page }) => {
  const seen = watch(page);
  const response = await page.goto("/");
  const headers = response.headers();
  expect(headers["content-security-policy"]).toContain("script-src 'self'");
  expect(headers["x-content-type-options"]).toBe("nosniff");
  expect(headers["x-frame-options"]).toBe("DENY");
  await expect(page.locator("h1")).toContainText("find your first open-source contribution");
  await expect(page.locator("#stepper li")).toHaveCount(4);

  // Tailwind's build is applied (a utility class works) and the self-hosted fonts really loaded.
  expect(await page.evaluate(() => getComputedStyle(document.querySelector(".sr-only")).position)).toBe("absolute");
  expect(await page.evaluate(async () => { await document.fonts.ready; return document.fonts.check("700 16px 'Atkinson Hyperlegible'") && document.fonts.check("800 16px 'Bricolage Grotesque'"); })).toBe(true);
  await openIssues(page);
  expect(seen.foreign).toEqual([]);
  expect(seen.problems).toEqual([]);
});

test("search ignores one character, order and load more reach the server", async ({ page, request }) => {
  const seen = watch(page);
  await control(request, "set", { paged: "1" });
  await openIssues(page, ["python"]);
  await expect(cards(page)).toHaveCount(9); // 6 Python (a full page) plus one each from JavaScript, TypeScript and Go
  await expect(page.locator("#load-more")).toBeVisible();
  await page.locator("#load-more").click();
  await expect(cards(page)).toHaveCount(11); // plus the two on Python's second page
  await expect(page.locator("#load-more")).toBeHidden(); // that page was short, so there is no third
  expect(seen.requests.some((r) => /\/api\/issues\?page=2$/.test(r.url))).toBe(true);

  await page.locator("#search-input").fill("i");
  await page.waitForTimeout(700);
  expect(seen.requests.some((r) => /[?&]q=i(&|$)/.test(r.url))).toBe(false);
  await page.locator("#search-input").fill("zz");
  await page.waitForRequest((r) => /[?&]q=zz/.test(r.url()));

  await Promise.all([page.waitForRequest((r) => /sort=newest/.test(r.url())), page.locator("#sort-select").selectOption("newest")]);
  expect(seen.problems).toEqual([]);
});

test("inspect an issue, read the problem, follow the steps, and the progress is remembered", async ({ page }) => {
  const seen = watch(page);
  await openIssues(page);
  await expect(page.locator("#progress-detail")).toContainText("You have not started an issue yet");
  await page.locator(`${CARD} button:has-text("Inspect issue")`).click();

  await expect(page.locator("#layer-3")).toBeVisible();
  await expect(page.locator("#check-panel")).toContainText("Healthy");
  await expect(page.locator("#understand-panel")).toContainText(TITLE);
  await expect(page.locator("#approach-panel")).toContainText("src/pyparse/ics.py");
  await expect(page.locator("#guide-slot")).toContainText("Comment on the issue to claim it."); // arrives after the rest, from TinyFish
  expect(seen.requests.filter((r) => r.url.endsWith("/api/guide")).length).toBe(1);

  await expect(page.locator("#to-steps")).toHaveAttribute("aria-disabled", "false");
  await page.locator("#to-steps").click();
  await expect(page.locator("#layer-4")).toBeVisible();
  await expect(page.locator("#start-panel .plan-steps > li")).toHaveCount(8);
  await page.locator("#plan-1001-1").check();

  await page.locator('#stepper button[data-layer="2"]').click();
  await expect(page.locator("#progress-label")).toHaveText("Onboarding Progress: 13% Complete");
  await expect(page.locator("#progress-detail")).toContainText("1 of 8 steps done on the 1 issue you started");

  await page.goto("/#step-2"); // a fresh page load: the progress comes back from this browser's storage
  await page.reload();
  await expect(cards(page).first()).toBeVisible();
  await expect(page.locator("#progress-label")).toHaveText("Onboarding Progress: 13% Complete");
  expect(seen.foreign).toEqual([]);
  expect(seen.problems).toEqual([]);
});

test("bookmarks belong to one browser, send only the link, and survive a reload", async ({ page, browser }) => {
  const seen = watch(page);
  await openIssues(page);
  const star = page.locator(`${CARD} .bookmark-btn`);
  await star.click();
  await expect(star).toHaveAttribute("aria-pressed", "true"); // instantly, before the server answers
  await expect(page.locator("#bookmark-count")).toHaveText("1");
  await expect(page.locator("#toast")).toContainText("Saved to bookmarks");
  const post = seen.requests.find((r) => r.method === "POST" && r.url.endsWith("/api/bookmarks"));
  expect(JSON.parse(post.body)).toEqual({ github_url: "https://github.com/acme/pyparse/issues/11" }); // nothing else is sent

  await page.goto("/#step-2");
  await page.reload();
  await expect(page.locator(`${CARD} .bookmark-btn`)).toHaveAttribute("aria-pressed", "true");
  await page.locator("#view-bookmarks").click();
  await expect(page.locator("#bookmark-grid")).toContainText(TITLE);

  const stranger = await browser.newContext(); // another person's browser: no cookie, so no bookmarks
  const other = await stranger.newPage();
  await other.goto("/#bookmarks");
  await expect(other.locator("#bookmark-grid")).toContainText("No bookmarks yet");
  await stranger.close();

  await page.locator("#bookmark-grid .bookmark-btn").click();
  await expect(page.locator("#bookmark-grid")).toContainText("No bookmarks yet");
  expect(seen.problems).toEqual([]);
});

test("a save that fails is rolled back and says why", async ({ page, request }) => {
  const seen = watch(page, { allowFailedRequests: true });
  await openIssues(page);
  await control(request, "set", { down: "1" }); // the list is already on screen; saving needs GitHub
  const star = page.locator(`${CARD} .bookmark-btn`);
  await star.click();
  await expect(page.locator("#toast")).toContainText("Could not save the bookmark");
  await expect(page.locator("#toast")).toContainText("Could not reach GitHub");
  await expect(star).toHaveAttribute("aria-pressed", "false");
  await expect(page.locator("#bookmark-count")).toBeHidden();
  expect(seen.problems).toEqual([]);
});

test("GitHub's rate limit reads as a plain message with a way to try again", async ({ page, request }) => {
  watch(page, { allowFailedRequests: true });
  await openIssues(page);
  await control(request, "set", { rate_limited: "1" });
  await page.locator("#search-input").fill(`fresh${Date.now()}`);
  await expect(page.locator("#issue-error")).toContainText("rate limit");
  await expect(page.locator("#issue-error button")).toHaveText("Try again");
  await control(request, "set", { rate_limited: "0" });
  await page.locator("#issue-error button").click();
  await expect(cards(page).first()).toBeVisible();
});

test("the layout fits a phone: no sideways scrolling on any step", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await openIssues(page);
  const overflow = () => page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(await overflow()).toBeLessThanOrEqual(1);
  await page.locator(`${CARD} button:has-text("Inspect issue")`).click();
  await expect(page.locator("#check-panel")).toContainText("Healthy");
  expect(await overflow()).toBeLessThanOrEqual(1);
});

test("no accessibility violations on the first three steps, colour contrast included", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" }); // axe would measure text that is still fading in as half transparent
  await page.addInitScript({ content: axeSource }); // injected over the DevTools protocol, so the page's own security policy does not block it
  const scan = async (name) => {
    const result = await page.evaluate(() => window.axe.run(document, { resultTypes: ["violations"] }));
    const found = result.violations.map((v) => `${v.id}: ${v.nodes.length} element(s), e.g. ${v.nodes[0].target.join(" ")}`);
    expect({ step: name, found }).toEqual({ step: name, found: [] });
  };
  await page.goto("/");
  await scan("1 Your skills");
  await openIssues(page);
  await scan("2 Pick an issue");
  await page.locator(`${CARD} button:has-text("Inspect issue")`).click();
  await expect(page.locator("#guide-slot")).toContainText("claim it");
  await scan("3 The problem");
});
