import { useMemo } from "react";
import { VOICE_LABEL } from "../lib/voice";
import { useTasks } from "../stores/tasks";
import type { VoiceState } from "../types";
import { IconMic, IconStop } from "./icons";

/** A shape per state, so the state never depends on colour alone (PRD §10.5). */
function StateGlyph({ state }: { state: VoiceState }) {
  return <span aria-hidden className={`voice-glyph voice-glyph-${state}`}><i /><i /><i /></span>;
}

/**
 * PRD §4.3 / §11.2: always-visible voice state, an explicit "mic on" indicator while audio goes to Gemini,
 * the mic button (start / end the session) and the last lines of the conversation. On any AI problem it
 * says so in words and the rest of the panel keeps working (manual mode).
 */
export function VoiceBar({ onSetup }: { onSetup: () => void }) {
  const voice = useTasks((s) => s.voice);
  const hasKey = useTasks((s) => s.hasKey);
  const transcript = useTasks((s) => s.transcript);
  const toggleVoice = useTasks((s) => s.toggleVoice);
  const state: VoiceState = voice?.state ?? "idle";
  const active = Boolean(voice?.mic_active) || state === "processing" || state === "speaking";
  const recent = useMemo(() => transcript.slice(-3), [transcript]);
  const showLines = recent.length > 0 && state !== "idle" && state !== "muted";

  // No key yet (or it was removed): one clear line and a way to fix it, instead of a big onboarding card.
  if (hasKey === false && !active) {
    return (
      <section aria-label="Voice" className="glass flex items-center gap-2.5 rounded-3xl px-3 py-2">
        <StateGlyph state="muted" />
        <div className="min-w-0 flex-1">
          <p className="truncate text-xs font-semibold text-fg">Voice is off</p>
          <p className="truncate text-[11px] text-muted">Add your Gemini API key to talk to Ziko</p>
        </div>
        <button type="button" onClick={onSetup} className="btn-cta shrink-0 px-3 py-1.5 text-xs">Add key</button>
      </section>
    );
  }

  return (
    <section aria-label="Voice" className={`glass rounded-3xl px-3 py-2 ${state === "error" ? "border-danger/40" : ""}`}>
      <div className="flex items-center gap-2.5">
        <StateGlyph state={state} />
        <div className="min-w-0 flex-1" aria-live="polite">
          <p className={`truncate text-xs font-semibold ${state === "error" ? "text-danger" : "text-fg"}`}>{VOICE_LABEL[state]}</p>
          <p className="truncate text-[11px] text-muted" title={state === "error" ? voice?.error?.message : undefined}>
            {state === "error"
              ? voice?.error?.message
              : state === "muted"
                ? "Unmute from the dot or tray to talk to Ziko"
                : state === "idle"
                  ? "Say “Hey Ziko”, press the mic, or type a question"
                  : state === "listening"
                    ? `Mic turns off after ${voice?.silence_timeout_s ?? 10} s of silence`
                    : null}
          </p>
        </div>
        {voice?.mic_active && (
          <span className="chip shrink-0 bg-[#e11d48] text-white" title="Microphone audio is being sent to Gemini">
            <span aria-hidden className="h-1.5 w-1.5 animate-pulse rounded-full bg-white" />
            Mic on
          </span>
        )}
        <button
          type="button"
          onClick={() => void toggleVoice()}
          disabled={voice?.muted}
          aria-pressed={active}
          aria-label={active ? "End voice conversation" : "Talk to Ziko"}
          title={active ? "End conversation" : "Talk to Ziko"}
          className={active ? "icon-btn !text-danger" : "btn-cta !h-9 !w-9 !p-0"}
        >
          {active ? <IconStop /> : <IconMic />}
        </button>
      </div>
      {showLines && (
        <ol aria-label="Conversation" className="mt-2 flex flex-col gap-1 border-t border-line pt-2 text-xs">
          {recent.map((l, i) => (
            <li key={i} className={l.role === "user" ? "self-end text-right text-muted" : "text-fg"}>
              <span className="sr-only">{l.role === "user" ? "You: " : "Ziko: "}</span>
              {l.text}
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}
