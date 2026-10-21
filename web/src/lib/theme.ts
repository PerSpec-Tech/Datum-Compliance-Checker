import { useEffect, useState } from "react";

// Dark is the default for tools (guidelines §2); light is the user's choice, remembered per browser.
export type Theme = "dark" | "light";
const KEY = "cc.theme";
const EVENT = "cc-theme";

export function storedTheme(): Theme {
  try {
    return localStorage.getItem(KEY) === "light" ? "light" : "dark";
  } catch {
    return "dark";
  }
}

export function applyTheme(t: Theme) {
  if (t === "light") document.documentElement.dataset.theme = "light";
  else delete document.documentElement.dataset.theme;
  document.querySelector('meta[name="theme-color"]')?.setAttribute("content", t === "light" ? "#ffffff" : "#000000");
}

export function setTheme(t: Theme) {
  try {
    localStorage.setItem(KEY, t);
  } catch {
    /* storage unavailable: the choice lasts this visit */
  }
  applyTheme(t);
  window.dispatchEvent(new CustomEvent(EVENT, { detail: t }));
}

export function useTheme(): Theme {
  const [t, setT] = useState<Theme>(storedTheme);
  useEffect(() => {
    const on = (e: Event) => setT((e as CustomEvent<Theme>).detail);
    window.addEventListener(EVENT, on);
    return () => window.removeEventListener(EVENT, on);
  }, []);
  return t;
}

/** A design token's current value, e.g. css("--text-primary") → "#f2f2f3". */
export function css(name: string): string {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}
