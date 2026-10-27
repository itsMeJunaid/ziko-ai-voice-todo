import { ErrorBoundary } from "./components/ErrorBoundary";
import { FloatingDot } from "./components/FloatingDot";
import { PetPreview } from "./components/PetPreview";
import { TaskPanel } from "./components/TaskPanel";

/** Each Tauri window loads index.html with a hash route: #/dot or #/panel. A plain browser shows the panel. */
export default function App() {
  const route = window.location.hash.replace("#/", "");
  if (import.meta.env.DEV && route === "pet-preview") return <PetPreview />;
  if (route === "dot") {
    return (
      <ErrorBoundary variant="dot">
        <FloatingDot />
      </ErrorBoundary>
    );
  }
  return (
    <ErrorBoundary variant="panel">
      <TaskPanel />
    </ErrorBoundary>
  );
}
