/**
 * Time helpers. The backend stores UTC; the user sees wall time in their configured zone
 * (undefined → system zone). Inputs use naive "YYYY-MM-DDTHH:mm" wall-time strings.
 */

function parts(d: Date, tz?: string) {
  const f = new Intl.DateTimeFormat("en-CA", {
    timeZone: tz,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
  });
  const p = Object.fromEntries(f.formatToParts(d).map((x) => [x.type, x.value]));
  return { y: p.year, m: p.month, d: p.day, h: p.hour, min: p.minute };
}

/** "2026-10-27" in the given zone. */
export function dateKey(d: Date, tz?: string): string {
  const p = parts(d, tz);
  return `${p.y}-${p.m}-${p.d}`;
}

/** UTC ISO → value for <input type="datetime-local"> in the user's zone. */
export function toInputValue(iso: string | null, tz?: string): string {
  if (!iso) return "";
  const p = parts(new Date(iso), tz);
  return `${p.y}-${p.m}-${p.d}T${p.h}:${p.min}`;
}

/** Shift a naive wall-time string by minutes (wall-clock arithmetic; DST edges are the backend's job). */
export function shiftWallTime(value: string, minutes: number): string {
  const d = new Date(`${value}:00Z`);
  d.setUTCMinutes(d.getUTCMinutes() + minutes);
  return d.toISOString().slice(0, 16);
}

/** Minutes between two naive wall-time strings (b − a). */
export function wallDiffMinutes(a: string, b: string): number {
  return Math.round((new Date(`${b}:00Z`).getTime() - new Date(`${a}:00Z`).getTime()) / 60000);
}

export function formatTime(iso: string, tz?: string): string {
  return new Intl.DateTimeFormat(undefined, { timeZone: tz, hour: "numeric", minute: "2-digit" }).format(
    new Date(iso),
  );
}

/** "10:00 AM" today, "Tomorrow 9:00 AM", "Yesterday 4:00 PM", else "Fri 31 Oct, 9:00 AM". */
export function formatDue(iso: string, tz?: string, now: Date = new Date()): string {
  const d = new Date(iso);
  const key = dateKey(d, tz);
  const today = dateKey(now, tz);
  const tomorrow = dateKey(new Date(now.getTime() + 86_400_000), tz);
  const yesterday = dateKey(new Date(now.getTime() - 86_400_000), tz);
  const t = formatTime(iso, tz);
  if (key === today) return t;
  if (key === tomorrow) return `Tomorrow ${t}`;
  if (key === yesterday) return `Yesterday ${t}`;
  const day = new Intl.DateTimeFormat(undefined, {
    timeZone: tz,
    weekday: "short",
    day: "numeric",
    month: "short",
  }).format(d);
  return `${day}, ${t}`;
}

export function greeting(now: Date, tz?: string): string {
  const h = Number(parts(now, tz).h);
  if (h < 5) return "Working late";
  if (h < 12) return "Good morning";
  if (h < 17) return "Good afternoon";
  return "Good evening";
}

export function formatHeaderDate(now: Date, tz?: string): string {
  return new Intl.DateTimeFormat(undefined, { timeZone: tz, weekday: "long", day: "numeric", month: "long" }).format(
    now,
  );
}

export function formatClock(now: Date, tz?: string): string {
  return new Intl.DateTimeFormat(undefined, { timeZone: tz, hour: "numeric", minute: "2-digit" }).format(now);
}
