import { useSyncExternalStore } from "react";

let preference;
function getPreference() {
  if (!preference && typeof window !== "undefined") {
    preference = window.matchMedia("(prefers-reduced-motion: reduce)");
  }
  return preference;
}
const subscribe = (listener) => {
  const query = getPreference();
  query?.addEventListener("change", listener);
  return () => query?.removeEventListener("change", listener);
};
const snapshot = () => getPreference()?.matches ?? false;

// Reacts immediately when the OS preference changes during an open session.
export function useReducedMotion() {
  return useSyncExternalStore(subscribe, snapshot, () => false);
}
