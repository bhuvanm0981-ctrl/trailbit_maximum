/* Things that go wrong in the real world: hostile content, blocked storage, a dead network, a bad proxy, odd URLs, odd input. */
const { test, expect } = require("@playwright/test");
const { CARD, control, watch, cards, openIssues, overflow } = require("./helpers");

test.beforeEach(async ({ request }) => { await control(request, "reset"); });

const HOSTILE_CARD = '#issue-groups article[data-issue-id="7001"]';

test("hostile GitHub content is shown as plain text and never runs", async ({ page, request }) => {
  const seen = watch(page);
  await control(request, "set", { hostile: "1" });
  await page.goto("/");
  const scriptsAtLoad = await page.evaluate(() => document.scripts.length);
  await page.locator("#continue-skills").click();
  await expect(page.locator(HOSTILE_CARD)).toBeVisible();
  await expect(page.locator(`${HOSTILE_CARD} h4`)).toHaveText('<img src=x onerror="window.__pwned=1"> Hostile title'); // the characters, not an image

  await page.locator(`${HOSTILE_CARD} button:has-text("Inspect issue")`).click();
  await expect(page.locator("#check-panel")).toContainText("Open pull request");
  await expect(page.locator("#understand-panel")).toContainText("<script>window.__pwned=1</script>"); // the summary, as text
  await expect(page.locator("#guide-slot")).toContainText("Comment on the issue to claim it.");
  await page.locator("#to-steps").click();
  await expect(page.locator("#start-panel .plan-steps > li")).toHaveCount(8);
  await page.locator("#view-bookmarks").click();

  expect(await page.evaluate(() => window.__pwned)).toBeUndefined(); // nothing ran
  expect(await page.evaluate(() => document.scripts.length)).toBe(scriptsAtLoad); // nothing injected a script
  expect(await page.locator('img[src="x"], svg[onload]').count()).toBe(0);
  expect(await page.locator("a[href^='javascript:' i]").count()).toBe(0);
  expect(seen.dialogs).toEqual([]);
  expect(seen.problems).toEqual([]);
});

test("the app still works when the browser blocks local storage (private modes, strict settings)", async ({ page }) => {
  await page.addInitScript(() => {
    const deny = () => { throw new DOMException("The operation is insecure.", "SecurityError"); };
    Object.defineProperty(window, "localStorage", { get: deny });
    Object.defineProperty(window, "sessionStorage", { get: deny });
  });
  const seen = watch(page);
  await openIssues(page, ["python"]);
  await page.locator(`${CARD} button:has-text("Inspect issue")`).click();
  await expect(page.locator("#check-panel")).toContainText("Healthy");
  await page.locator("#to-steps").click();
  await page.locator("#plan-1001-1").check();
  await page.locator('#stepper button[data-layer="2"]').click();
  await expect(page.locator("#progress-label")).toHaveText("Onboarding Progress: 13% Complete"); // kept for this visit, just not saved
  expect(seen.problems).toEqual([]);
});

test("no connection: the page says so in plain words and recovers when the connection returns", async ({ page, context }) => {
  const seen = watch(page, { allowFailedRequests: true });
  await openIssues(page);
  await context.setOffline(true);
  await page.locator(`${CARD} button:has-text("Inspect issue")`).click();
  await expect(page.locator("#check-panel")).toContainText("Could not reach the Trailbit server");
  await expect(page.locator("#start-panel")).toContainText("Could not reach the Trailbit server");
  await expect(page.locator("#layer-3")).toBeVisible(); // still a working page, no blank screen
  await page.locator("#back-to-issues").click();
  await page.locator("#search-input").fill("while offline");
  await expect(page.locator("#issue-error")).toContainText("Could not reach the Trailbit server");
  await context.setOffline(false);
  await page.locator("#issue-error button").click(); // Try again
  await expect(cards(page).first()).toBeVisible();
  expect(seen.problems.filter((p) => p.startsWith("pageerror"))).toEqual([]);
});

test("a proxy error page is reported, not shown as raw code", async ({ page }) => {
  const seen = watch(page, { allowFailedRequests: true });
  await page.route("**/api/issues**", (route) => route.fulfill({ status: 502, contentType: "text/html", body: "<html><body>Bad gateway</body></html>" }));
  await page.goto("/");
  await page.locator("#continue-skills").click();
  await expect(page.locator("#issue-error")).toContainText("The server returned an error (502)");
  await page.unroute("**/api/issues**");
  await page.route("**/api/issues**", (route) => route.fulfill({ status: 200, contentType: "text/html", body: "<html><body>Welcome to my captive portal</body></html>" }));
  await page.locator("#issue-error button").click();
  await expect(page.locator("#issue-error")).toContainText("could not read the server's reply");
  await expect(page.locator("#issue-error")).not.toContainText("Unexpected token"); // no parser jargon
  await page.unroute("**/api/issues**");
  await page.locator("#issue-error button").click();
  await expect(cards(page).first()).toBeVisible();
  expect(seen.problems.filter((p) => p.startsWith("pageerror"))).toEqual([]);
});

test("browser Back and Forward walk through the steps, and the selection survives", async ({ page }) => {
  const seen = watch(page);
  await page.goto("/");
  await expect(page.locator("#layer-1")).toBeVisible();
  await page.locator("#continue-skills").click();
  await expect(cards(page).first()).toBeVisible();
  await page.locator(`${CARD} button:has-text("Inspect issue")`).click();
  await expect(page.locator("#layer-3")).toBeVisible();
  await expect(page.locator("#check-panel")).toContainText("Healthy");

  await page.goBack();
  await expect(page.locator("#layer-2")).toBeVisible();
  await page.goBack();
  await expect(page.locator("#layer-1")).toBeVisible();
  await page.goForward();
  await page.goForward();
  await expect(page.locator("#layer-3")).toBeVisible();
  await expect(page.locator("#check-panel")).toContainText("Healthy");
  expect(seen.problems).toEqual([]);
});

test("hand-typed addresses never break the page", async ({ page }) => {
  const seen = watch(page);
  for (const hash of ["#step-9", "#step-0", "#step-4", "#step-x", "#step-", "#step-12", "#STEP-2", "#bookmarks", "#nonsense", "#%E0%A4%A", "#step-2%00"]) {
    await page.goto(`/${hash}`);
    await page.waitForLoadState("networkidle");
    const visible = await page.locator("main section.layer:not([hidden]), #bookmarks-view:not([hidden])").count();
    expect(visible, hash).toBeGreaterThanOrEqual(1);
  }
  // With an issue chosen, an out-of-range step is clamped to the nearest real one.
  await openIssues(page);
  await page.locator(`${CARD} button:has-text("Inspect issue")`).click();
  await expect(page.locator("#check-panel")).toContainText("Healthy");
  await page.evaluate(() => { location.hash = "#step-9"; });
  await expect(page.locator("#layer-4")).toBeVisible();
  await page.evaluate(() => { location.hash = "#step-0"; });
  await expect(page.locator("#layer-1")).toBeVisible();
  expect(seen.problems).toEqual([]);
});

test("a bookmark star works from the keyboard", async ({ page }) => {
  watch(page);
  await openIssues(page);
  const star = page.locator(`${CARD} .bookmark-btn`);
  await star.focus();
  await page.keyboard.press("Enter");
  await expect(star).toHaveAttribute("aria-pressed", "true");
  await expect(page.locator("#toast")).toContainText("Saved to bookmarks");
  await page.keyboard.press("Space");
  await expect(star).toHaveAttribute("aria-pressed", "false");
});

test("the stepper and Inspect button work from the keyboard, and focus moves to the new step's heading", async ({ page }) => {
  watch(page);
  await openIssues(page);
  await page.locator(`${CARD} button:has-text("Inspect issue")`).focus();
  await page.keyboard.press("Enter");
  await expect(page.locator("#layer-3")).toBeVisible();
  await expect(page.locator("#l3-title")).toBeFocused(); // a screen reader user hears where they are
  await page.locator('#stepper button[data-layer="2"]').focus();
  await page.keyboard.press("Enter");
  await expect(page.locator("#layer-2")).toBeVisible();
  await expect(page.locator("#l2-title")).toBeFocused();
});

test("saving a bookmark twice in a hurry leaves the page and the server in agreement", async ({ page }) => {
  const seen = watch(page);
  await openIssues(page);
  const star = page.locator(`${CARD} .bookmark-btn`);
  await star.dblclick();
  await page.waitForTimeout(900);
  const onPage = (await star.getAttribute("aria-pressed")) === "true";
  const onServer = (await (await page.request.get("/api/bookmarks")).json()).some((b) => b.id === "1001");
  expect(onPage).toBe(onServer);
  expect(await page.locator("#bookmark-count").isVisible()).toBe(onServer);
  expect(seen.problems).toEqual([]);
});

test("typing a search quickly and mashing the controls raises no errors and ends on a full list", async ({ page }) => {
  const seen = watch(page);
  await openIssues(page);
  const search = page.locator("#search-input");
  for (const text of ["a", "ab", "abc", "ab", "a", "", "xyz", "xy"]) await search.fill(text);
  for (const sort of ["newest", "discussed", "quiet", "updated", "newest"]) await page.locator("#sort-select").selectOption(sort);
  await page.locator("#change-skills").click();
  await page.locator("#continue-skills").click();
  await expect(cards(page).first()).toBeVisible();
  await expect(page.locator("#issue-groups[aria-busy='false']")).toBeVisible();
  expect(seen.problems).toEqual([]);
});

for (const [width, height] of [[320, 568], [375, 667], [768, 1024], [1024, 768], [1920, 1080]]) {
  test(`all four steps fit a ${width}x${height} screen, with no sideways scrolling`, async ({ page }) => {
    await page.emulateMedia({ reducedMotion: "reduce" }); // measure the layout at rest, not mid slide-in
    await page.setViewportSize({ width, height });
    const seen = watch(page);
    await page.goto("/");
    expect(await overflow(page), "step 1").toBeLessThanOrEqual(1);
    await page.locator("#continue-skills").click();
    await expect(cards(page).first()).toBeVisible();
    expect(await overflow(page), "step 2").toBeLessThanOrEqual(1);
    await page.locator(`${CARD} button:has-text("Inspect issue")`).click();
    await expect(page.locator("#check-panel")).toContainText("Healthy");
    expect(await overflow(page), "step 3").toBeLessThanOrEqual(1);
    await page.locator("#to-steps").click();
    await expect(page.locator("#start-panel .plan-steps > li")).toHaveCount(8);
    expect(await overflow(page), "step 4").toBeLessThanOrEqual(1);
    await page.locator("#view-bookmarks").click();
    expect(await overflow(page), "bookmarks").toBeLessThanOrEqual(1);
    expect(seen.problems).toEqual([]);
  });
}
