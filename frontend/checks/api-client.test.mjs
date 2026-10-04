import assert from "node:assert/strict";
import test from "node:test";
import { fetchModels, normalizeResponse, queryApi } from "../src/services/apiClient.js";

// A stand-in for window.fetch: records each call and answers with `reply`.
function fakeFetch(reply) {
  const calls = [];
  const fetchImpl = async (url, init = {}) => {
    calls.push({ url, init });
    if (reply instanceof Error) throw reply;
    return reply;
  };
  return { calls, fetchImpl };
}

function jsonReply(status, body) {
  return { ok: status < 400, status, json: async () => body };
}

const SUCCESS = {
  status: "success",
  sql: "SELECT count(*) AS films FROM film LIMIT 1000",
  message: "**Films**: 1,000.",
  tables: [{ id: "result", title: "How many films?", columns: [{ key: "films", label: "Films", type: "number" }], rows: [{ films: 1000 }] }],
  visualizations: [{ id: "answer-kpi", type: "kpi", title: "How many films?" }],
  kpis: [{ id: "answer", label: "Films", value: 1000, type: "number" }],
  error: null
};

test("questions go to POST /api/query with the chosen model", async () => {
  const { calls, fetchImpl } = fakeFetch(jsonReply(200, SUCCESS));
  const response = await queryApi({ prompt: "How many films?", modelId: "gemini", csrfToken: "t" }, { baseUrl: "https://api.example/", fetchImpl });
  assert.equal(calls[0].url, "https://api.example/api/query");
  assert.equal(calls[0].init.method, "POST");
  assert.deepEqual(JSON.parse(calls[0].init.body), { question: "How many films?", model: "gemini" });
  assert.equal(response.status, "success");
  assert.equal(response.sql, SUCCESS.sql);
  assert.equal(response.tables[0].rows[0].films, 1000);
  assert.equal(response.kpis[0].value, 1000);
});

test("without a model the server default is used", async () => {
  const { calls, fetchImpl } = fakeFetch(jsonReply(200, SUCCESS));
  await queryApi({ prompt: "q", csrfToken: "t" }, { fetchImpl });
  assert.equal(calls[0].url, "/api/query");
  assert.deepEqual(JSON.parse(calls[0].init.body), { question: "q" });
});

test("refused queries keep the SQL and explain the refusal", async () => {
  const { fetchImpl } = fakeFetch(jsonReply(200, {
    status: "error", sql: "DELETE FROM film", message: "", tables: [], visualizations: [], kpis: [],
    error: { code: "rejected", message: "Only SELECT queries are allowed, got DELETE.", retryable: false }
  }));
  const response = await queryApi({ prompt: "Delete every film", csrfToken: "t" }, { fetchImpl });
  assert.equal(response.status, "error");
  assert.equal(response.sql, "DELETE FROM film");
  assert.equal(response.error.retryable, false);
  assert.match(response.error.message, /isn't allowed to run/);
  assert.match(response.error.message, /got DELETE/);
});

test("outages are retryable and keep the server's safe message", async () => {
  const { fetchImpl } = fakeFetch(jsonReply(503, {
    status: "error", sql: "", message: "", tables: [], visualizations: [], kpis: [], error: { code: "model_unavailable", message: "The language model is not reachable right now.", retryable: true }
  }));
  const response = await queryApi({ prompt: "q", csrfToken: "t" }, { fetchImpl });
  assert.equal(response.error.code, "model_unavailable");
  assert.equal(response.error.retryable, true);
  assert.equal(response.error.message, "The language model is not reachable right now.");
});

test("rate limits, bad questions, proxy pages and network failures become friendly errors", async () => {
  const limited = await queryApi({ prompt: "q", csrfToken: "t" }, fakeFetch(jsonReply(429, null)));
  assert.equal(limited.error.code, "rate_limited");
  assert.equal(limited.error.retryable, true);

  const invalid = await queryApi({ prompt: "x".repeat(3000), csrfToken: "t" }, fakeFetch(jsonReply(422, { detail: [] })));
  assert.equal(invalid.error.code, "invalid_question");
  assert.equal(invalid.error.retryable, false);

  const htmlPage = { ok: false, status: 504, json: async () => { throw new SyntaxError("Unexpected token <"); } };
  const timedOut = await queryApi({ prompt: "q", csrfToken: "t" }, fakeFetch(htmlPage));
  assert.equal(timedOut.error.code, "unavailable");
  assert.equal(timedOut.error.retryable, true);

  const offline = await queryApi({ prompt: "q", csrfToken: "t" }, fakeFetch(new TypeError("Failed to fetch")));
  assert.equal(offline.error.code, "unavailable");
});

test("cancelling a question rejects with AbortError instead of showing an error", async () => {
  const abort = new DOMException("The operation was aborted.", "AbortError");
  await assert.rejects(queryApi({ prompt: "q", csrfToken: "t" }, fakeFetch(abort)), { name: "AbortError" });
});

test("only well-formed replies become answers; anything else is a retryable error", () => {
  const full = normalizeResponse({ status: "success", message: "Hi", tables: [], visualizations: [], kpis: [] });
  assert.deepEqual(full, { status: "success", sql: "", model: "", message: "Hi", tables: [], visualizations: [], kpis: [] });
  for (const bad of [null, { status: "success", message: "Hi" }, { status: "done", message: "", tables: [], visualizations: [], kpis: [] }]) {
    const response = normalizeResponse(bad);
    assert.equal(response.status, "error");
    assert.equal(response.error.retryable, true);
  }
});

test("sign-in problems become sign_in_required or access_denied, and no CSRF token means no request", async () => {
  const noToken = fakeFetch(jsonReply(200, SUCCESS));
  const withoutToken = await queryApi({ prompt: "q" }, noToken);
  assert.equal(withoutToken.error.code, "sign_in_required");
  assert.equal(noToken.calls.length, 0);

  const ended = await queryApi({ prompt: "q", csrfToken: "t" }, fakeFetch(jsonReply(401, { detail: "x" })));
  assert.equal(ended.error.code, "sign_in_required");
  const denied = await queryApi({ prompt: "q", csrfToken: "t" }, fakeFetch(jsonReply(403, { detail: "x" })));
  assert.equal(denied.error.code, "access_denied");
  assert.equal(denied.error.retryable, false);
});

test("the CSRF token and session cookie travel with every question", async () => {
  const { calls, fetchImpl } = fakeFetch(jsonReply(200, SUCCESS));
  await queryApi({ prompt: "q", csrfToken: "session-csrf" }, { fetchImpl });
  assert.equal(calls[0].init.headers["X-CSRF-Token"], "session-csrf");
  assert.equal(calls[0].init.credentials, "same-origin");
  assert.equal(calls[0].init.cache, "no-store");
});

test("models come from GET /api/models, server default first, and failures give an empty list", async () => {
  const models = [{ id: "gemini", name: "gemma-4-31b-it", description: "Google Gemini API" }, { id: "ollama", name: "qwen3:8b", description: "" }, { bad: true }];
  const { calls, fetchImpl } = fakeFetch(jsonReply(200, { models }));
  const listed = await fetchModels({ fetchImpl });
  assert.equal(calls[0].url, "/api/models");
  assert.deepEqual(listed.map((model) => model.id), ["gemini", "ollama"]);

  assert.deepEqual(await fetchModels(fakeFetch(jsonReply(500, null))), []);
  assert.deepEqual(await fetchModels(fakeFetch(new TypeError("offline"))), []);
});

test("the answering model is kept, so a fallback to Ollama is visible", async () => {
  const { fetchImpl } = fakeFetch(jsonReply(200, { ...SUCCESS, model: "qwen3:8b" }));
  const response = await queryApi({ prompt: "q", modelId: "gemini", csrfToken: "t" }, { fetchImpl });
  assert.equal(response.model, "qwen3:8b");
});
