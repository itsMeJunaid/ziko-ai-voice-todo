import type { AppSettings } from "../types";

/**
 * Apply backend appearance settings to this window: the pet's size and opacity, in the dot window only.
 */
export function applyAppearance(a: AppSettings["appearance"], { dot }: { dot: boolean }): void {
  const root = document.documentElement.style;
  if (dot) {
    root.setProperty("--pet-size", `${Math.min(52, Math.max(32, a.dot_size))}px`); // the 64 px window fits ≤ 52
    root.setProperty("--pet-opacity", String(Math.min(1, Math.max(0.2, a.dot_opacity))));
  }
}
