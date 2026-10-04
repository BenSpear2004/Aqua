// Vite exposes only this public demo switch. Live requests use this site's /api.
// VITE_AQUA_USE_MOCK is the older name for the same switch.
const env = import.meta.env ?? {};
export const DEMO_MODE = env.VITE_AQUA_DEMO_MODE === "true" || env.VITE_AQUA_USE_MOCK === "true";
