// Read by the Tailwind CLI (npm run build:css). These tokens used to live in an inline <script> in index.html.
module.exports = {
  content: ["./frontend/index.html", "./frontend/js/**/*.js"],
  theme: {
    extend: {
      // Semantic colours read CSS variables from style.css, so a different palette (or the dark footer) re-points them.
      colors: {
        ink: { DEFAULT: "var(--ink)", body: "var(--body)", muted: "var(--muted)" },
        line: "rgb(var(--line-rgb) / <alpha-value>)",
        teal: { DEFAULT: "rgb(var(--accent-rgb) / <alpha-value>)", deep: "var(--accent-deep)" },
      },
      fontFamily: {
        sans: ['"Atkinson Hyperlegible"', "ui-sans-serif", "system-ui", "sans-serif"],
        display: ['"Bricolage Grotesque"', '"Instrument Sans"', "ui-sans-serif", "system-ui", "sans-serif"],
        mono: ['"JetBrains Mono"', "ui-monospace", "SFMono-Regular", "Menlo", "monospace"],
      },
    },
  },
};
