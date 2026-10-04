// The one entry point components use for answers and model choices.
// Demo mode (VITE_AQUA_DEMO_MODE=true, or a demoMode option) swaps in the
// offline mock (mockClient.js) for UI work without the backend or sign-in.
// Live requests go to /api on this origin, which the Vite dev proxy and the
// production nginx both forward, and carry the session's CSRF token.
import { fetchModels, queryApi } from "./apiClient.js";
import * as mock from "./mockClient.js";
import { AI_MODELS } from "../mocks/aiModels.js";
import { DEMO_MODE } from "./runtimeConfig.js";

function useMock(options) {
  return options.demoMode ?? DEMO_MODE;
}

export function sendMessage(options) {
  return useMock(options) ? mock.sendMessage(options) : queryApi(options);
}

// The backend has no separate retry route: a retry asks the same question again.
export function retryMessage(options) {
  return useMock(options) ? mock.retryMessage(options) : queryApi(options);
}

export function listModels(options = {}) {
  return useMock(options) ? Promise.resolve(AI_MODELS) : fetchModels(options);
}
