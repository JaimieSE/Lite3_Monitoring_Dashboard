import type { Config } from "tailwindcss";

// Colours are CSS variables defined in src/app/globals.css (single source of truth).
const v = (name: string) => `rgb(var(--${name}) / <alpha-value>)`;

const config: Config = {
  content: ["./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        bg: v("bg"),
        panel: v("panel"),
        panel2: v("panel2"),
        line: v("line"),
        ink: v("ink"),
        muted: v("muted"),
        faint: v("faint"),
        good: v("good"),
        warn: v("warn"),
        serious: v("serious"),
        crit: v("crit"),
        s1: v("s1"),
        s2: v("s2"),
        s3: v("s3"),
        s4: v("s4"),
        s5: v("s5"),
        s7: v("s7"),
      },
      fontFamily: {
        sans: ["Inter", "ui-sans-serif", "system-ui", "-apple-system", "Segoe UI", "sans-serif"],
        mono: ["JetBrains Mono", "SF Mono", "ui-monospace", "Menlo", "monospace"],
      },
      fontSize: { "2xs": ["0.6875rem", "1rem"] },
    },
  },
  plugins: [],
};
export default config;
