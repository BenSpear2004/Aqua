import assert from "node:assert/strict";
import test from "node:test";
import { retryMessage, sendMessage } from "../src/services/aquaClient.js";

const RESULT = {
  status: "success",
  sql: "SELECT count(*) AS count FROM film LIMIT 1000",
  message: "Found 1000 films.",
  tables: [{ id: "result", title: "Result", columns: [{ key: "count", label: "Count", type: "number" }], rows: [{ count: 1000 }] }],
  visualizations: [],
  kpis: [],
  error: null
};

function jsonResponse(body, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

for (const [name, request] of [["send", sendMessage], ["retry", retryMessage]]) {
  test(`${name} routes live queries through the authenticated relative API`, async (t) => {
    const requests = [];
    t.mock.method(globalThis, "fetch", async (url, init) => {
      requests.push({ url, init });
      return jsonResponse(RESULT);
    });
    const controller = new AbortController();
    const response = await request({
      prompt: "How many films?", csrfToken: "session-csrf", signal: controller.signal, demoMode: false,
      conversationId: "conversation-a", requestId: "request-a", modelId: "qwen3:8b"
    });
    assert.equal(requests.length, 1);
    const { url, init } = requests[0];
    assert.equal(url, "/api/query");
    assert.equal(init.method, "POST");
    assert.equal(init.credentials, "same-origin");
    assert.equal(init.cache, "no-store");
    assert.equal(init.signal, controller.signal);
    assert.equal(new Headers(init.headers).get("Content-Type"), "application/json");
    assert.equal(new Headers(init.headers).get("X-CSRF-Token"), "session-csrf");
    assert.deepEqual(JSON.parse(init.body), { question: "How many films?" });
    assert.equal(response.status, "success");
    assert.equal(response.sql, RESULT.sql);
    assert.equal(response.message, RESULT.message);
    assert.deepEqual(response.tables, RESULT.tables);
  });
}

test("live requests without CSRF never call the network", async (t) => {
  const fetch = t.mock.method(globalThis, "fetch", async () => { throw new Error("No request expected"); });
  for (const request of [sendMessage, retryMessage]) {
    const response = await request({ prompt: "List customers", demoMode: false });
    assert.equal(response.status, "error");
    assert.equal(response.error.code, "sign_in_required");
    assert.equal(response.error.retryable, false);
  }
  assert.equal(fetch.mock.callCount(), 0);
});

test("requests use the live API by default", async (t) => {
  const fetch = t.mock.method(globalThis, "fetch", async () => jsonResponse(RESULT));
  const response = await sendMessage({ prompt: "How many films?", csrfToken: "csrf" });
  assert.equal(response.sql, RESULT.sql);
  assert.equal(fetch.mock.callCount(), 1);
});

for (const [status, code, retryable] of [[401, "sign_in_required", false], [403, "access_denied", false], [503, "unavailable", true]]) {
  test(`live HTTP ${status} produces a safe ${code} response`, async (t) => {
    t.mock.method(globalThis, "fetch", async () => jsonResponse({ detail: "private database host or bearer token" }, status));
    const response = await sendMessage({ prompt: "q", csrfToken: "csrf", demoMode: false });
    assert.equal(response.status, "error");
    assert.equal(response.error.code, code);
    assert.equal(response.error.retryable, retryable);
    assert.doesNotMatch(JSON.stringify(response), /private database host|bearer token/);
  });
}

test("a live network failure returns a safe service error", async (t) => {
  t.mock.method(globalThis, "fetch", async () => { throw new TypeError("private backend network address"); });
  const response = await sendMessage({ prompt: "q", csrfToken: "csrf", demoMode: false });
  assert.equal(response.status, "error");
  assert.equal(response.error.retryable, true);
  assert.doesNotMatch(JSON.stringify(response), /private backend network address/);
});

test("live cancellation is propagated rather than rendered as a failed query", async (t) => {
  const cancelled = new DOMException("Request cancelled", "AbortError");
  t.mock.method(globalThis, "fetch", async () => { throw cancelled; });
  await assert.rejects(sendMessage({ prompt: "q", csrfToken: "csrf", demoMode: false, signal: new AbortController().signal }), (error) => error === cancelled);
});

test("a rejected SQL result stays an error without losing its SQL", async (t) => {
  const rejected = { ...RESULT, status: "error", sql: "DELETE FROM film", message: "private rejection detail", tables: [], error: { code: "rejected", message: "private database diagnostic", retryable: false } };
  t.mock.method(globalThis, "fetch", async () => jsonResponse(rejected));
  const response = await sendMessage({ prompt: "Delete films", csrfToken: "csrf", demoMode: false });
  assert.equal(response.status, "error");
  assert.equal(response.sql, rejected.sql);
  assert.equal(response.error.code, "query_failed");
  assert.equal(response.error.retryable, false);
  assert.doesNotMatch(JSON.stringify(response), /private rejection detail|private database diagnostic/);
});

test("a malformed successful response cannot be rendered as valid customer data", async (t) => {
  t.mock.method(globalThis, "fetch", async () => jsonResponse({ status: "success", message: "private malformed result", tables: "unexpected" }));
  const response = await sendMessage({ prompt: "q", csrfToken: "csrf", demoMode: false });
  assert.equal(response.status, "error");
  assert.equal(response.error.retryable, true);
  assert.deepEqual(response.tables, []);
  assert.doesNotMatch(JSON.stringify(response), /private malformed result/);
});

test("explicit demo mode keeps callbacks and avoids customer API requests", async (t) => {
  const fetch = t.mock.method(globalThis, "fetch", async () => { throw new Error("Demo must not query a customer database"); });
  const fragments = [];
  const response = await sendMessage({
    prompt: "Show expenses by category", demoMode: true, conversationId: "demo-conversation", requestId: "demo-request",
    onFirstContent: (fragment, context) => fragments.push({ fragment, context }),
    onContent: (fragment, context) => fragments.push({ fragment, context })
  });
  assert.equal(response.status, "success");
  assert.ok(fragments.length);
  assert.equal(fragments.at(-1).fragment.message, response.message);
  assert.deepEqual(fragments[0].context, { conversationId: "demo-conversation", requestId: "demo-request" });
  assert.equal(fetch.mock.callCount(), 0);
});
