import { useEffect } from "react";
import { readPref, usePref } from "./prefs";

export type Theme = "dark" | "light";
export const THEMES = ["dark", "light"] as const;
const KEY = "ziko.theme";

const apply = (t: Theme) => (document.documentElement.dataset.theme = t);

export function useTheme(): [Theme, (t: Theme) => void] {
  const [theme, setTheme] = usePref<Theme>(KEY, THEMES, "dark");
  useEffect(() => void apply(theme), [theme]);
  return [theme, setTheme];
}

apply(readPref<Theme>(KEY, THEMES, "dark")); // before first paint: no flash of the wrong theme
