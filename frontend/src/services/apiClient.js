// The real transport: POST /api/query and GET /api/models on the backend.
// Everything API-specific stays here, so components only ever see the
// normalized response shape documented in BACKEND_INTEGRATION.md.

const TOO_FAST = "You're asking questions faster than AQUA can answer them. Wait a moment and try again.";
const UNREACHABLE = "AQUA couldn't reach its server. Check your connection and try again.";
const BAD_QUESTION = "That question is empty or too long. Keep it under 2,000 characters.";
const SIGN_IN = "Please sign in to ask AQUA a question.";
const SESSION_ENDED = "Your session has ended. Please sign in again.";
const NO_ACCESS = "Your account cannot access this data right now. Please check your access and try again.";

function errorResponse(code, message, retryable, sql = "") {
  return { status: "error", sql, message: "", tables: [], visualizations: [], kpis: [], error: { code, message, retryable } };
}

// Validator and database refusals carry a reason the user can act on; the
// prefix says what happened in plain words before the technical reason.
const ERROR_PREFIX = {
  rejected: "AQUA wrote a query it isn't allowed to run, so nothing was executed.",
  query_failed: "The database couldn't run AQUA's query."
};

function asArray(value) {
  return Array.isArray(value) ? value : [];
}

// A reply that is not the documented shape is never rendered as data: it
// could be a proxy page, a partial body, or a bug, and showing it as a
// table would mislead. It becomes a retryable error instead.
function wellFormed(body) {
  return Boolean(body) && typeof body === "object"
    && ["success", "error"].includes(body.status)
    && typeof body.message === "string"
    && ["tables", "visualizations", "kpis"].every((key) => Array.isArray(body[key]));
}

export function normalizeResponse(body) {
  if (!wellFormed(body)) return errorResponse("unavailable", UNREACHABLE, true);
  const sql = typeof body.sql === "string" ? body.sql : "";
  if (body.status === "error") {
    const code = body.error?.code || "unexpected";
    const reason = typeof body.error?.message === "string" ? body.error.message : "";
    const message = ERROR_PREFIX[code] ? `${ERROR_PREFIX[code]} ${reason}`.trim() : reason || UNREACHABLE;
    return errorResponse(code, message, Boolean(body.error?.retryable), sql);
  }
  return {
    status: "success",
    sql,
    // The model that actually answered; differs from the one chosen when
    // the server fell back to Ollama because Gemini was unavailable.
    model: typeof body.model === "string" ? body.model : "",
    message: typeof body.message === "string" ? body.message : "",
    tables: asArray(body.tables),
    visualizations: asArray(body.visualizations),
    kpis: asArray(body.kpis)
  };
}

function apiUrl(baseUrl, path) {
  return `${(baseUrl || "").replace(/\/+$/, "")}${path}`;
}

// Questions need a signed-in session: the cookie travels with the request,
// and the CSRF token from /api/auth goes in a header the backend checks.
// 401 and 403 come back as sign_in_required and access_denied, which
// useChat answers by refreshing the sign-in state.
export async function queryApi(
  { prompt, modelId, csrfToken, signal },
  { baseUrl = "", fetchImpl = globalThis.fetch } = {}
) {
  if (signal?.aborted) throw new DOMException("Request cancelled", "AbortError");
  if (!csrfToken) return errorResponse("sign_in_required", SIGN_IN, false);
  let response;
  try {
    response = await fetchImpl(apiUrl(baseUrl, "/api/query"), {
      method: "POST",
      credentials: "same-origin",
      cache: "no-store",
      headers: { "Content-Type": "application/json", Accept: "application/json", "X-CSRF-Token": csrfToken },
      body: JSON.stringify({ question: prompt, ...(modelId ? { model: modelId } : {}) }),
      signal
    });
  } catch (error) {
    if (error?.name === "AbortError") throw error;
    return errorResponse("unavailable", UNREACHABLE, true);
  }

  if (response.status === 401) return errorResponse("sign_in_required", SESSION_ENDED, false);
  if (response.status === 403) return errorResponse("access_denied", NO_ACCESS, false);
  if (response.status === 429) return errorResponse("rate_limited", TOO_FAST, true);
  if (response.status === 422) return errorResponse("invalid_question", BAD_QUESTION, false);

  let body = null;
  try {
    body = await response.json();
  } catch (error) {
    if (error?.name === "AbortError") throw error;
    // A proxy timeout or crash page instead of the backend's JSON.
    return errorResponse("unavailable", UNREACHABLE, true);
  }
  return normalizeResponse(body);
}

export async function fetchModels({ baseUrl = "", fetchImpl = globalThis.fetch, signal } = {}) {
  try {
    const response = await fetchImpl(apiUrl(baseUrl, "/api/models"), {
      credentials: "same-origin", cache: "no-store", headers: { Accept: "application/json" }, signal
    });
    if (!response.ok) return [];
    const body = await response.json();
    return asArray(body?.models).filter((model) => model && typeof model.id === "string" && typeof model.name === "string");
  } catch (error) {
    if (error?.name === "AbortError") throw error;
    return [];
  }
}
