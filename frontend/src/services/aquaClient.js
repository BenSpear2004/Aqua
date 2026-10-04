import { createMockResponse } from "../mocks/mockResponses.js";
import { DEMO_MODE } from "./runtimeConfig.js";

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

// Keep all transport/mock timing here. Optional callbacks exercise a cumulative
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

function safeError(code, message, retryable = false) {
  return { status: "error", message: "", sql: "", tables: [], visualizations: [], kpis: [], error: { code, message, retryable } };
}

async function liveRequest({ prompt, csrfToken, signal }) {
  if (signal?.aborted) throw new DOMException("Request cancelled", "AbortError");
  if (!csrfToken) return safeError("sign_in_required", "Please sign in to ask AQUA a question.");
  try {
    const response = await fetch("/api/query", {
      method: "POST", credentials: "same-origin", cache: "no-store", signal,
      headers: { "Content-Type": "application/json", "X-CSRF-Token": csrfToken },
      body: JSON.stringify({ question: prompt })
    });
    if (response.status === 401) return safeError("sign_in_required", "Your session has ended. Please sign in again.");
    if (response.status === 403) return safeError("access_denied", "Your account cannot access this data right now. Please check your access and try again.");
    if (response.status === 422) return safeError("invalid_question", "Enter a question of up to 2,000 characters.");
    if (!response.ok) return safeError("unavailable", "AQUA couldn't complete that request. Please try again.", true);
    const body = await response.json();
    if (!["success", "error"].includes(body?.status) || typeof body.message !== "string"
      || !["tables", "visualizations", "kpis"].every((key) => Array.isArray(body[key]))) {
      return safeError("unavailable", "AQUA couldn't complete that request. Please try again.", true);
    }
    if (body.status === "error") {
      return { ...safeError("query_failed", "AQUA couldn't answer that question. Try rephrasing it."), sql: typeof body.sql === "string" ? body.sql : "" };
    }
    return { status: "success", message: body.message, sql: typeof body.sql === "string" ? body.sql : "", tables: body.tables, visualizations: body.visualizations, kpis: body.kpis, error: null };
  } catch (error) {
    if (error?.name === "AbortError") throw error;
    return safeError("unavailable", "AQUA couldn't complete that request. Please try again.", true);
  }
}

export function sendMessage(options) {
  return (options.demoMode ?? DEMO_MODE) ? mockRequest(options) : liveRequest(options);
}

export function retryMessage(options) {
  return (options.demoMode ?? DEMO_MODE) ? mockRequest(options, true) : liveRequest(options);
}
