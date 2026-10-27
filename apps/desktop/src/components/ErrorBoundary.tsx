import { Component } from "react";
import type { ErrorInfo, ReactNode } from "react";

/**
 * A render error must never leave an invisible dot or a blank panel (PRD §12 "recover safely").
 * The fallback is deliberately dependency-free: plain DOM, a reload action, nothing that can throw again.
 */
export class ErrorBoundary extends Component<{ variant: "dot" | "panel"; children: ReactNode }, { failed: boolean }> {
  state = { failed: false };

  static getDerivedStateFromError() {
    return { failed: true };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error(`[${this.props.variant}] render error`, error, info.componentStack);
  }

  render() {
    if (!this.state.failed) return this.props.children;
    if (this.props.variant === "dot") {
      return (
        <div className="grid h-full w-full place-items-center">
          <button type="button" onClick={() => location.reload()} aria-label="Ziko hit a problem. Click to reload." title="Ziko hit a problem — click to reload" className="h-11 w-11 rounded-2xl border-2 border-danger bg-[#18191c]" />
        </div>
      );
    }
    return (
      <div className="h-full w-full p-2">
        <div role="alert" className="shell flex h-full flex-col items-center justify-center gap-3 p-6 text-center">
          <p className="text-sm font-medium text-fg">Something went wrong in the panel.</p>
          <p className="text-xs text-muted">Your tasks are safe — they are stored locally.</p>
          <button type="button" className="btn-cta" onClick={() => location.reload()}>Reload panel</button>
        </div>
      </div>
    );
  }
}
