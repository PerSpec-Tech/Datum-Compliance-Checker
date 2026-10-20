/** @type {import('tailwindcss').Config} */
// Colours, radii and type come from the PerSpec design tokens in src/index.css (UI-UX guidelines).
const v = (name) => `var(--${name})`;
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    colors: {
      transparent: "transparent",
      current: "currentColor",
      white: "#ffffff",
      black: "#000000",
      canvas: v("bg-canvas"),
      surface: { low: v("bg-surface-low"), DEFAULT: v("bg-surface"), raised: v("bg-surface-raised"), overlay: v("bg-overlay") },
      line: { subtle: v("border-subtle"), DEFAULT: v("border-default"), strong: v("border-strong") },
      fg: { DEFAULT: v("text-primary"), 2: v("text-secondary"), 3: v("text-tertiary"), off: v("text-disabled") },
      accent: { DEFAULT: v("accent"), ink: v("accent-ink") },
      cyan: { 400: v("data-cyan-400"), 700: v("data-cyan-700"), 800: v("data-cyan-800") },
      magenta: { 400: v("data-magenta-400"), 700: v("data-magenta-700"), 800: v("data-magenta-800") },
      danger: v("danger"),
      success: v("success"),
    },
    borderRadius: { none: "0", sm: "2px", DEFAULT: "2px", md: "4px", lg: "6px", full: "9999px" },
    fontFamily: { sans: ["var(--font-ui)"], mono: ["var(--font-mono)"] },
    extend: {
      fontSize: { "2xs": ["11px", "14px"] },
      transitionTimingFunction: { DEFAULT: "cubic-bezier(0.2, 0, 0, 1)" },
      transitionDuration: { DEFAULT: "120ms" },
    },
  },
  plugins: [],
};
