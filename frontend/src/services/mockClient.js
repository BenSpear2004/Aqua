import { createMockResponse } from "../mocks/mockResponses.js";

const MOCK_DELAY_MS = 1050;
const STREAM_STEP_MS = 85;

function wait(delay, signal) {
  return new Promise((resolve, reject) => {
    if (signal?.aborted) {
      reject(new DOMException("Request cancelled", "AbortError"));
      return;
    }
    const abort = () => {
      globalThis.clearTimeout(timer);
      reject(new DOMException("Request cancelled", "AbortError"));
    };
    const timer = globalThis.setTimeout(() => {
      signal?.removeEventListener("abort", abort);
      resolve();
    }, delay);
    signal?.addEventListener("abort", abort, { once: true });
  });
}

// Offline stand-in for the API, used when VITE_AQUA_USE_MOCK=true and by the
// UI checks. Keep all mock timing here. Optional callbacks exercise a cumulative
// text stream; the Promise still resolves the original complete response shape.
async function mockRequest({ prompt, conversationId, requestId, modelId, signal, onFirstContent, onContent }, retrying = false) {
  await wait(MOCK_DELAY_MS, signal);
  const query = retrying ? prompt.replace(/\b(error|fail|retry)\b/gi, "financial") : prompt;
  const response = createMockResponse(query);
  if (response.status !== "success" || (!onFirstContent && !onContent)) return response;

  const message = response.message ?? "";
  const steps = Math.min(6, Math.max(1, Math.ceil(message.length / 65)));
  const context = { conversationId, requestId, ...(modelId ? { modelId } : {}) };
  for (let step = 1; step <= steps; step += 1) {
    if (signal?.aborted) throw new DOMException("Request cancelled", "AbortError");
    const fragment = { status: "streaming", message: message.slice(0, Math.ceil(message.length * step / steps)), tables: [], visualizations: [], kpis: [] };
    if (step === 1) (onFirstContent ?? onContent)?.(fragment, context);
    else onContent?.(fragment, context);
    if (step < steps) await wait(STREAM_STEP_MS, signal);
  }
  if (signal?.aborted) throw new DOMException("Request cancelled", "AbortError");
  return response;
}

export function sendMessage(options) {
  return mockRequest(options);
}

export function retryMessage(options) {
  return mockRequest(options, true);
}
