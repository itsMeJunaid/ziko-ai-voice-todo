/**
 * See-through glass, done per platform so nothing breaks:
 *  - Windows: real OS blur of the wallpaper behind the panel (Mica on Windows 11, Acrylic on 10),
 *    with native rounded corners via the DWM shadow.
 *  - Linux / macOS / browser: the window is transparent and the panel is a translucent tint, so the
 *    wallpaper shows through (CSS cannot blur outside the page; Linux has no standard blur API).
 *  - No compositor (Linux X11 without one): transparent pixels render black → force an opaque panel
 *    that fills the window edge to edge.
 */
import { useEffect, useState } from "react";
import { usePref } from "./prefs";
import type { Theme } from "./theme";

export type GlassPref = "auto" | "frosted" | "clear" | "solid";
export type Glass = "frosted" | "clear" | "solid";
export const GLASS_PREFS = ["auto", "frosted", "clear", "solid"] as const;

export interface GlassSupport {
  os: string; // "windows" | "linux" | "macos" | "browser"
  compositor: boolean;
  session?: string | null;
  win11?: boolean;
}

/** Pure: what the panel actually renders for a preference on this platform. */
export function resolveGlass(pref: GlassPref, s: GlassSupport): Glass {
  if (!s.compositor) return "solid"; // transparency would show as black
  return pref === "auto" ? "frosted" : pref;
}

/** Pure: whether the OS (not CSS) provides the blur, and which effect. */
export function osEffect(glass: Glass, s: GlassSupport): "mica" | "acrylic" | null {
  if (glass !== "frosted" || s.os !== "windows") return null;
  return s.win11 ? "mica" : "acrylic";
}

export function describeGlass(pref: GlassPref, s: GlassSupport): string {
  const g = resolveGlass(pref, s);
  if (!s.compositor) return "No compositor detected — transparency is off so the panel can't render black.";
  const fx = osEffect(g, s);
  if (fx) return `Wallpaper blurred by Windows (${fx === "mica" ? "Mica" : "Acrylic"}).`;
  if (g === "frosted") return "Wallpaper shows through a soft tint.";
  if (g === "clear") return "Wallpaper shows through clearly. Cards stay readable.";
  return "Opaque panel, no transparency.";
}

async function detectSupport(): Promise<GlassSupport> {
  const isTauri = "__TAURI_INTERNALS__" in window;
  let s: GlassSupport = { os: "browser", compositor: true };
  if (isTauri) {
    try {
      const { invoke } = await import("@tauri-apps/api/core");
      s = await invoke<GlassSupport>("glass_support");
    } catch {
      s = { os: "unknown", compositor: true };
    }
  }
  if (s.os === "windows") {
    // UA says "Windows NT 10.0" on both 10 and 11; platformVersion ≥ 13 means Windows 11.
    try {
      const uad = (navigator as Navigator & { userAgentData?: { getHighEntropyValues(h: string[]): Promise<{ platformVersion?: string }> } }).userAgentData;
      const v = await uad?.getHighEntropyValues(["platformVersion"]);
      s.win11 = Number(v?.platformVersion?.split(".")[0] ?? 0) >= 13;
    } catch {
      s.win11 = false;
    }
  }
  return s;
}

let supportPromise: Promise<GlassSupport> | null = null;
export const getGlassSupport = () => (supportPromise ??= detectSupport());

async function applyNative(glass: Glass, theme: Theme, s: GlassSupport): Promise<void> {
  if (!("__TAURI_INTERNALS__" in window)) return;
  const { getCurrentWindow, Effect } = await import("@tauri-apps/api/window");
  const win = getCurrentWindow();
  const fx = osEffect(glass, s);
  try {
    if (fx === "mica") {
      await win.setEffects({ effects: [Effect.Mica] }); // follows the system light/dark; our CSS tint sets the theme
    } else if (fx === "acrylic") {
      const color: [number, number, number, number] = theme === "dark" ? [15, 16, 18, 150] : [245, 245, 247, 140];
      await win.setEffects({ effects: [Effect.Acrylic], color });
    } else {
      await win.clearEffects();
    }
    // Windows 11 gives undecorated windows native rounded corners only together with the shadow.
    if (s.os === "windows") await win.setShadow(fx !== null);
  } catch (e) {
    console.warn("window effects unavailable", e); // CSS tint still looks right
  }
}

/** Panel-window hook: preference + platform → data attributes for CSS + native effect. */
export function useGlass(theme: Theme): { pref: GlassPref; setPref: (p: GlassPref) => void; glass: Glass; support: GlassSupport | null } {
  const [pref, setPref] = usePref<GlassPref>("ziko.glass", GLASS_PREFS, "auto");
  const [support, setSupport] = useState<GlassSupport | null>(null);
  useEffect(() => void getGlassSupport().then(setSupport), []);
  const glass: Glass = support ? resolveGlass(pref, support) : "solid";

  useEffect(() => {
    if (!support) return;
    const el = document.documentElement;
    el.dataset.glass = glass;
    el.dataset.osblur = osEffect(glass, support) ? "1" : "0";
    el.dataset.compositor = support.compositor ? "1" : "0";
    void applyNative(glass, theme, support);
  }, [glass, theme, support]);

  return { pref, setPref, glass, support };
}
