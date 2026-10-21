import { setTheme, useTheme } from "../lib/theme";

export default function ThemeToggle() {
  const theme = useTheme();
  const next = theme === "dark" ? "light" : "dark";
  return (
    <button
      onClick={() => setTheme(next)}
      className="btn-ghost h-7 px-2"
      title={`${next} mode`}
      aria-label={`Switch to ${next} mode`}
    >
      <svg width="16" height="16" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden>
        {theme === "dark" ? (
          <>
            <circle cx="10" cy="10" r="3.5" />
            <path d="M10 2v2M10 16v2M2 10h2M16 10h2M4.3 4.3l1.4 1.4M14.3 14.3l1.4 1.4M4.3 15.7l1.4-1.4M14.3 5.7l1.4-1.4" />
          </>
        ) : (
          <path d="M16 12.5A7 7 0 0 1 7.5 4a7 7 0 1 0 8.5 8.5z" />
        )}
      </svg>
    </button>
  );
}
