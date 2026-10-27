import { useEffect, useState } from "react";

/**
 * Tiny UI preference store shared by the dot and panel windows (same origin → same localStorage;
 * the `storage` event syncs the other window). Phase 6 moves these into backend settings.
 */
export function readPref<T extends string>(key: string, allowed: readonly T[], fallback: T): T {
  try {
    const v = localStorage.getItem(key);
    if (v && (allowed as readonly string[]).includes(v)) return v as T;
  } catch {
    /* storage unavailable (private mode / preview) */
  }
  return fallback;
}

export function usePref<T extends string>(key: string, allowed: readonly T[], fallback: T): [T, (v: T) => void] {
  const [value, setValue] = useState<T>(() => readPref(key, allowed, fallback));
  useEffect(() => {
    const onStorage = (e: StorageEvent) => e.key === key && setValue(readPref(key, allowed, fallback));
    window.addEventListener("storage", onStorage);
    return () => window.removeEventListener("storage", onStorage);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);
  const set = (v: T) => {
    try {
      localStorage.setItem(key, v);
    } catch {
      /* non-persistent is acceptable */
    }
    setValue(v);
  };
  return [value, set];
}
