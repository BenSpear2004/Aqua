const UNAVAILABLE = "AQUA sign-in is temporarily unavailable. Please try again.";

export class AuthError extends Error {
  constructor(status, message = UNAVAILABLE) {
    super(message);
    this.name = "AuthError";
    this.status = status;
  }
}

function safeError(status) {
  if (status === 401) return new AuthError(status, "Your sign-in could not be verified. Please sign in again.");
  if (status === 403) return new AuthError(status, "Please start a new sign-in attempt and try again.");
  return new AuthError(status);
}

async function request(path, options = {}) {
  let response;
  try {
    response = await fetch(path, { credentials: "same-origin", cache: "no-store", ...options });
  } catch (error) {
    if (error?.name === "AbortError") throw error;
    throw new AuthError(503);
  }
  if (!response.ok) throw safeError(response.status);
  if (response.status === 204) return null;
  try {
    return await response.json();
  } catch (error) {
    if (error?.name === "AbortError") throw error;
    throw new AuthError(502);
  }
}

function sessionResponse(body) {
  const user = body?.user;
  if (!user || typeof user.sub !== "string" || !user.sub || typeof user.email !== "string"
    || typeof user.name !== "string" || typeof user.picture !== "string"
    || typeof body.csrf_token !== "string" || !body.csrf_token || typeof body.can_query !== "boolean") {
    throw new AuthError(502);
  }
  return { user: { sub: user.sub, email: user.email, name: user.name, picture: user.picture }, csrf_token: body.csrf_token, can_query: body.can_query };
}

export async function fetchAuthConfig({ signal } = {}) {
  const body = await request("/api/auth/config", { signal });
  if (!body || !["client_id", "nonce", "csrf_token"].every((key) => typeof body[key] === "string" && body[key])) {
    throw new AuthError(502);
  }
  return { client_id: body.client_id, nonce: body.nonce, csrf_token: body.csrf_token };
}

export async function fetchSession({ signal } = {}) {
  try {
    return sessionResponse(await request("/api/auth/me", { signal }));
  } catch (error) {
    if (error instanceof AuthError && error.status === 401) return null;
    throw error;
  }
}

export async function signInWithGoogle({ credential, csrfToken, signal }) {
  if (typeof credential !== "string" || !credential || typeof csrfToken !== "string" || !csrfToken) {
    throw new AuthError(401, "Please start a new sign-in attempt and try again.");
  }
  return sessionResponse(await request("/api/auth/google", {
    method: "POST", signal,
    headers: { "Content-Type": "application/json", "X-CSRF-Token": csrfToken },
    body: JSON.stringify({ credential })
  }));
}

export async function signOut({ csrfToken, signal }) {
  if (typeof csrfToken !== "string" || !csrfToken) throw safeError(401);
  await request("/api/auth/logout", { method: "POST", signal, headers: { "X-CSRF-Token": csrfToken } });
}
