import assert from "node:assert/strict";
import test from "node:test";
import { createInitialChatState, PROJECTS } from "../src/mocks/navigation.js";
import { sendMessage, retryMessage } from "../src/services/aquaClient.js";

test("project folders reference the same distinct centralized conversations", () => {
  const state = createInitialChatState();
  const ids = new Set(state.conversations.map((conversation) => conversation.id));
  assert.equal(ids.size, state.conversations.length);
  assert.equal(state.conversations.find((conversation) => conversation.id === state.activeConversationId).messages.length, 0);
  function checkFolder(folder) {
    for (const id of folder.conversationIds) assert.ok(ids.has(id), `Missing conversation ${id}`);
    for (const child of folder.children) checkFolder(child);
  }
  PROJECTS.forEach(checkFolder);
  const replies = state.conversations.flatMap((conversation) => conversation.messages.filter((message) => message.role === "aqua"));
  assert.equal(new Set(replies.map((reply) => reply.response.message)).size, replies.length);
  const q3 = state.conversations.find((conversation) => conversation.id === "q3-cash-flow");
  assert.equal(q3.messages[1].response.tables[0].rows.length, 3);
});

test("stream callbacks carry cumulative text and routing IDs before completed structured data", async () => {
  const fragments = [];
  const response = await sendMessage({
    prompt: "Show both expenses and cash flow in two tables.",
    conversationId: "conversation-a",
    requestId: "request-a",
    onFirstContent: (fragment, context) => fragments.push({ fragment, context, first: true }),
    onContent: (fragment, context) => fragments.push({ fragment, context })
  });
  assert.equal(response.status, "success");
  assert.equal(response.tables.length, 2);
  assert.equal(fragments.filter((entry) => entry.first).length, 1);
  for (let index = 0; index < fragments.length; index += 1) {
    const { fragment, context } = fragments[index];
    assert.equal(fragment.status, "streaming");
    assert.deepEqual(context, { conversationId: "conversation-a", requestId: "request-a" });
    assert.deepEqual(fragment.tables, []);
    assert.deepEqual(fragment.visualizations, []);
    assert.deepEqual(fragment.kpis, []);
    assert.ok(response.message.startsWith(fragment.message));
    if (index) assert.ok(fragment.message.startsWith(fragments[index - 1].fragment.message));
  }
  assert.equal(fragments.at(-1).fragment.message, response.message);
});

test("legacy promise requests, safe errors, retry and no-data remain supported", async () => {
  const [success, error, retry, empty] = await Promise.all([
    sendMessage({ prompt: "Show expenses by category." }),
    sendMessage({ prompt: "error" }),
    retryMessage({ prompt: "error" }),
    sendMessage({ prompt: "no matching" })
  ]);
  assert.equal(success.status, "success");
  assert.ok(success.tables.length);
  assert.equal(error.status, "error");
  assert.equal(error.error.retryable, true);
  assert.equal(retry.status, "success");
  assert.equal(empty.status, "success");
  assert.deepEqual(empty.tables, []);
  assert.match(empty.message, /No matching/);
});

test("abort stops both waiting requests and an active simulated stream", async () => {
  const waiting = new AbortController();
  const cancelled = sendMessage({ prompt: "expenses", signal: waiting.signal });
  waiting.abort();
  await assert.rejects(cancelled, { name: "AbortError" });

  const streaming = new AbortController();
  let first = 0;
  let subsequent = 0;
  await assert.rejects(sendMessage({
    prompt: "explain detailed", signal: streaming.signal,
    onFirstContent: () => { first += 1; streaming.abort(); },
    onContent: () => { subsequent += 1; }
  }), { name: "AbortError" });
  assert.equal(first, 1);
  assert.equal(subsequent, 0);
});
