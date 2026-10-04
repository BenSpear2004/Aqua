import assert from "node:assert/strict";
import test from "node:test";
import { AuthError, fetchAuthConfig, fetchSession, signInWithGoogle, signOut } from "../src/services/authClient.js";

const CONFIG = { client_id: "123-test.apps.googleusercontent.com", nonce: "browser-nonce", csrf_token: "login-csrf" };
const SESSION = {
  user: { sub: "109876543210987654321", email: "reader@gmail.com", name: "Aqua Reader", picture: "https://example.com/avatar.png" },
  csrf_token: "session-csrf",
  can_query: true
};

function jsonResponse(body, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

function checkRequest(init, method, signal) {
  assert.equal(init.method ?? "GET", method);
  assert.equal(init.credentials, "same-origin");
  assert.equal(init.cache, "no-store");
  assert.equal(init.signal, signal);
}

test("login configuration and restored identity use the relative private API", async (t) => {
  const requests = [];
  t.mock.method(globalThis, "fetch", async (url, init) => {
    requests.push({ url, init });
    return jsonResponse(url === "/api/auth/config" ? CONFIG : SESSION);
  });
  const controller = new AbortController();
  assert.deepEqual(await fetchAuthConfig({ signal: controller.signal }), CONFIG);
  assert.deepEqual(await fetchSession({ signal: controller.signal }), SESSION);
  assert.deepEqual(requests.map(({ url }) => url), ["/api/auth/config", "/api/auth/me"]);
  for (const { init } of requests) checkRequest(init, "GET", controller.signal);
});

test("a missing browser session returns null without exposing server detail", async (t) => {
  t.mock.method(globalThis, "fetch", async () => jsonResponse({ detail: "private session diagnostic" }, 401));
  assert.equal(await fetchSession(), null);
});

test("Google credential and CSRF stay in the POST body/header, and logout handles 204", async (t) => {
  const requests = [];
  t.mock.method(globalThis, "fetch", async (url, init) => {
    requests.push({ url, init });
    return url === "/api/auth/logout" ? new Response(null, { status: 204 }) : jsonResponse(SESSION);
  });
  const controller = new AbortController();
  assert.deepEqual(await signInWithGoogle({ credential: "private-google-token", csrfToken: CONFIG.csrf_token, signal: controller.signal }), SESSION);
  await signOut({ csrfToken: SESSION.csrf_token, signal: controller.signal });
  assert.deepEqual(requests.map(({ url }) => url), ["/api/auth/google", "/api/auth/logout"]);
  for (const { init } of requests) checkRequest(init, "POST", controller.signal);
  assert.deepEqual(JSON.parse(requests[0].init.body), { credential: "private-google-token" });
  assert.equal(new Headers(requests[0].init.headers).get("Content-Type"), "application/json");
  assert.equal(new Headers(requests[0].init.headers).get("X-CSRF-Token"), CONFIG.csrf_token);
  assert.equal(new Headers(requests[1].init.headers).get("X-CSRF-Token"), SESSION.csrf_token);
});

for (const status of [401, 403, 503]) {
  test(`auth HTTP ${status} produces a typed safe error`, async (t) => {
    t.mock.method(globalThis, "fetch", async () => jsonResponse({ detail: "private backend address and private-google-token" }, status));
    await assert.rejects(signInWithGoogle({ credential: "private-google-token", csrfToken: CONFIG.csrf_token }), (error) => {
      assert.ok(error instanceof AuthError);
      assert.equal(error.status, status);
      assert.ok(error.message);
      assert.doesNotMatch(error.message, /private|backend address|google-token/);
      return true;
    });
  });
}

for (const [label, invalidSession] of [
  ["missing CSRF", { ...SESSION, csrf_token: "" }],
  ["missing Google subject", { ...SESSION, user: { ...SESSION.user, sub: "" } }],
  ["invalid permission flag", { ...SESSION, can_query: "yes" }],
  ["missing identity", { detail: "private malformed payload" }]
]) {
  test(`invalid session envelope is rejected: ${label}`, async (t) => {
    t.mock.method(globalThis, "fetch", async () => jsonResponse(invalidSession));
    await assert.rejects(fetchSession(), (error) => {
      assert.ok(error instanceof AuthError);
      assert.equal(error.status, 502);
      assert.doesNotMatch(error.message, /private malformed payload/);
      return true;
    });
  });
}

test("login configuration must contain a browser nonce", async (t) => {
  t.mock.method(globalThis, "fetch", async () => jsonResponse({ client_id: CONFIG.client_id, csrf_token: CONFIG.csrf_token }));
  await assert.rejects(fetchAuthConfig(), (error) => error instanceof AuthError && error.status === 502);
});

test("missing login credentials or logout CSRF never call the network", async (t) => {
  const fetch = t.mock.method(globalThis, "fetch", async () => { throw new Error("No authentication request expected"); });
  await assert.rejects(signInWithGoogle({ credential: "", csrfToken: CONFIG.csrf_token }), AuthError);
  await assert.rejects(signInWithGoogle({ credential: "token", csrfToken: "" }), AuthError);
  await assert.rejects(signOut({ csrfToken: "" }), AuthError);
  assert.equal(fetch.mock.callCount(), 0);
});

test("auth malformed JSON and network failures produce safe typed errors", async (t) => {
  const fetch = t.mock.method(globalThis, "fetch", async () => new Response("private invalid JSON", { status: 200 }));
  await assert.rejects(fetchAuthConfig(), (error) => error instanceof AuthError && !error.message.includes("private"));
  fetch.mock.mockImplementation(async () => { throw new TypeError("private network address"); });
  await assert.rejects(fetchSession(), (error) => error instanceof AuthError && !error.message.includes("private"));
});

test("cancelled auth requests propagate AbortError unchanged", async (t) => {
  const cancelled = new DOMException("Request cancelled", "AbortError");
  t.mock.method(globalThis, "fetch", async () => { throw cancelled; });
  await assert.rejects(fetchSession({ signal: new AbortController().signal }), (error) => error === cancelled);
});
