import type { Config } from "tailwindcss";

/**
 * Tokens are read straight from the CSS variables in globals.css.
 *
 * They used to be wrapped as `hsl(var(--background))` while globals.css
 * defined them as `oklch(...)` - which produces `hsl(oklch(1 0 0))`, invalid
 * CSS, so every semantic colour silently resolved to transparent or black.
 * Reading the variable directly means the stylesheet can use any colour space
 * and the two halves cannot drift apart again.
 */
const config: Config = {
  darkMode: ["class"],
  content: [
    "./pages/**/*.{js,ts,jsx,tsx,mdx}",
    "./components/**/*.{js,ts,jsx,tsx,mdx}",
    "./app/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      colors: {
        paper: "var(--paper)",
        background: "var(--background)",
        foreground: "var(--foreground)",
        card: {
          DEFAULT: "var(--card)",
          foreground: "var(--card-foreground)",
        },
        popover: {
          DEFAULT: "var(--popover)",
          foreground: "var(--popover-foreground)",
        },
        primary: {
          DEFAULT: "var(--primary)",
          foreground: "var(--primary-foreground)",
        },
        secondary: {
          DEFAULT: "var(--secondary)",
          foreground: "var(--secondary-foreground)",
        },
        muted: {
          DEFAULT: "var(--muted)",
          foreground: "var(--muted-foreground)",
        },
        accent: {
          DEFAULT: "var(--accent)",
          foreground: "var(--accent-foreground)",
        },
        destructive: "var(--destructive)",
        border: "var(--border)",
        input: "var(--input)",
        ring: "var(--ring)",

        // Dose states. Semantic and deliberately separate from the accent.
        taken: { DEFAULT: "var(--taken)", soft: "var(--taken-soft)" },
        late: { DEFAULT: "var(--late)", soft: "var(--late-soft)" },
        missed: { DEFAULT: "var(--missed)", soft: "var(--missed-soft)" },
        pending: { DEFAULT: "var(--pending)", soft: "var(--pending-soft)" },
        live: { DEFAULT: "var(--live)", soft: "var(--live-soft)" },
      },
      fontFamily: {
        // A grotesque with real figures for the interface, an editorial serif
        // for the one number that matters, and a mono for clock times so they
        // line up down a column.
        sans: ["var(--font-sans)", "ui-sans-serif", "system-ui", "sans-serif"],
        display: ["var(--font-display)", "Georgia", "serif"],
        mono: ["var(--font-mono)", "ui-monospace", "SFMono-Regular", "monospace"],
        urdu: ["var(--font-urdu)", "Noto Naskh Arabic", "serif"],
      },
      borderRadius: {
        lg: "var(--radius)",
        md: "calc(var(--radius) - 2px)",
        sm: "calc(var(--radius) - 4px)",
      },
      boxShadow: {
        card: "0 1px 2px rgb(21 24 26 / 0.04), 0 8px 24px -16px rgb(21 24 26 / 0.18)",
        lift: "0 2px 4px rgb(21 24 26 / 0.05), 0 16px 40px -24px rgb(21 24 26 / 0.25)",
      },
      letterSpacing: {
        label: "0.09em",
      },
    },
  },
  plugins: [require("tailwindcss-animate")],
};
export default config;
