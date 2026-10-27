import { useState } from "react";
import { errorText, useTasks } from "../stores/tasks";

type Result = { kind: "ok" | "error"; text: string; offline?: boolean } | null;

/**
 * Paste → test → save (PLAN Phase 6 onboarding). The key is tested before it is stored, so a typo never
 * replaces a working key. It goes to the OS credential store via the backend and is never shown again.
 */
export function KeyForm({ onSaved, compact = false }: { onSaved?: () => void; compact?: boolean }) {
  const api = useTasks((s) => s.api);
  const [key, setKey] = useState("");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<Result>(null);

  const save = async (skipTest = false) => {
    const k = key.trim();
    if (!api || k.length < 20 || busy) return;
    setBusy(true);
    setResult(null);
    try {
      if (!skipTest) {
        const t = await api.testKey(k);
        if (!t.ok) {
          setResult({ kind: "error", text: t.message, offline: t.code === "offline" });
          return;
        }
      }
      await api.setApiKey(k);
      setKey("");
      setResult({ kind: "ok", text: skipTest ? "Key saved. It will be checked when you next talk to Ziko." : "Connected. Voice is ready." });
      onSaved?.();
    } catch (e) {
      setResult({ kind: "error", text: errorText(e) });
    } finally {
      setBusy(false);
    }
  };

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        void save();
      }}
      className="flex flex-col gap-2"
    >
      <label htmlFor="api-key" className={compact ? "sr-only" : "label"}>Gemini API key</label>
      <div className="flex gap-2">
        <input
          id="api-key"
          type="password"
          autoComplete="off"
          spellCheck={false}
          value={key}
          onChange={(e) => {
            setKey(e.target.value);
            setResult(null);
          }}
          placeholder="Paste your key (starts with AIza…)"
          className="field min-w-0 flex-1"
        />
        <button type="submit" disabled={busy || key.trim().length < 20} className="btn-cta shrink-0 px-3 text-xs">
          {busy ? "Testing…" : "Save & test"}
        </button>
      </div>
      {result && (
        <p role="status" className={`text-[11px] font-medium ${result.kind === "ok" ? "text-fg" : "text-danger"}`}>
          {result.kind === "ok" ? "✓ " : ""}
          {result.text}
          {result.offline && (
            <button type="button" onClick={() => void save(true)} className="ml-1 underline">Save anyway</button>
          )}
        </p>
      )}
    </form>
  );
}
