// The one entry point components use for answers and model choices.
// VITE_AQUA_USE_MOCK=true swaps in the offline mock (mockClient.js), so the
// UI can be worked on without the backend. VITE_AQUA_API_BASE_URL points at a
// backend on another origin; left unset, requests go to /api on this origin,
// which the Vite dev proxy and the production nginx both forward.
import { fetchModels, queryApi } from "./apiClient.js";
import * as mock from "./mockClient.js";
import { AI_MODELS } from "../mocks/aiModels.js";

const env = import.meta.env ?? {};
export const USE_MOCK = env.VITE_AQUA_USE_MOCK === "true";
const BASE_URL = env.VITE_AQUA_API_BASE_URL || "";

export function sendMessage(options) {
  return USE_MOCK ? mock.sendMessage(options) : queryApi(options, { baseUrl: BASE_URL });
}

// The backend has no separate retry route: a retry asks the same question again.
export function retryMessage(options) {
  return USE_MOCK ? mock.retryMessage(options) : queryApi(options, { baseUrl: BASE_URL });
}

export function listModels(options = {}) {
  return USE_MOCK ? Promise.resolve(AI_MODELS) : fetchModels({ ...options, baseUrl: BASE_URL });
}
