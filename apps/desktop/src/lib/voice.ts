import type { TranscriptLine, VoiceState } from "../types";

const MAX_LINES = 20;

/**
 * Pure: fold one `voice.transcript` event into the conversation. Gemini streams a reply in chunks
 * (final=false) and closes it with an empty final event; typed user turns arrive whole (final=true).
 */
export function addTranscript(lines: TranscriptLine[], e: TranscriptLine): TranscriptLine[] {
  const out = lines.slice();
  const last = out[out.length - 1];
  const open = last && last.role === e.role && !last.final;
  if (open) out[out.length - 1] = { ...last, text: last.text + e.text, final: e.final };
  else if (e.text) out.push({ role: e.role, text: e.text, final: e.final });
  return out.slice(-MAX_LINES);
}

/** What the user reads for each state (PRD §4.3, §10.5: text, not colour alone). */
export const VOICE_LABEL: Record<VoiceState, string> = {
  idle: "Voice ready",
  listening: "Listening…",
  processing: "Thinking…",
  speaking: "Speaking…",
  interrupted: "Go ahead…",
  error: "AI offline — manual mode",
  muted: "Microphone muted",
};
