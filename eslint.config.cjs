const js = require("@eslint/js");
const globals = require("globals");

module.exports = [
  { ignores: ["node_modules/**", "frontend/tailwind.css", "frontend/fonts/**", "playwright-report/**", "test-results/**"] },
  js.configs.recommended,
  {
    files: ["frontend/js/**/*.js"],
    languageOptions: { ecmaVersion: 2023, sourceType: "module", globals: globals.browser },
    rules: { "no-unused-vars": ["error", { args: "none", caughtErrors: "none" }] },
  },
  {
    files: ["tests/e2e/**/*.js", "*.cjs"],
    languageOptions: { ecmaVersion: 2023, sourceType: "commonjs", globals: { ...globals.node, ...globals.browser } },
  },
];
