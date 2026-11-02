// Browser tests. Locally on Windows/macOS set PW_CHANNEL=msedge (or chrome) to use the browser you already have;
// in CI, `npx playwright install chromium` provides one. E2E_PYTHON points at the Python that has the backend installed.
const { defineConfig } = require("@playwright/test");

const PORT = Number(process.env.E2E_PORT || 8790);

module.exports = defineConfig({
  testDir: "tests/e2e",
  testMatch: "*.spec.js",
  timeout: 30_000,
  expect: { timeout: 8_000 },
  fullyParallel: false,
  workers: 1, // the test server holds state (a database, switches), so tests run one at a time
  reporter: process.env.CI ? [["github"], ["list"]] : [["list"]], // on GitHub, failures appear as annotations that name the test
  use: {
    baseURL: `http://127.0.0.1:${PORT}`,
    channel: process.env.PW_CHANNEL || undefined,
    trace: "retain-on-failure",
  },
  webServer: {
    command: `"${process.env.E2E_PYTHON || "python"}" tests/e2e/server.py`,
    url: `http://127.0.0.1:${PORT}/health`,
    reuseExistingServer: false,
    timeout: 60_000,
    env: { E2E_PORT: String(PORT) },
  },
});
