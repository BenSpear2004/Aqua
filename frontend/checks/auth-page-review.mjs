// Native Chrome/CDP review against an existing local Vite preview. No real auth/API calls.
import { spawn } from "node:child_process";
import { mkdtemp, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";

const artifactDir = await mkdtemp(path.join(tmpdir(), "aqua-auth-page-review-"));
const previewUrl = process.env.AQUA_REVIEW_URL || "http://localhost:5173";
const debuggingPort = 21000 + Math.floor(Math.random() * 10000);
const executable = process.env.AQUA_CHROME_EXECUTABLE || "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe";
const browser = spawn(executable, [
  "--headless=new", "--no-first-run", "--no-default-browser-check", "--disable-background-networking",
  "--disable-component-update", "--disable-sync", "--enable-unsafe-swiftshader",
  `--remote-debugging-port=${debuggingPort}`, `--user-data-dir=${path.join(artifactDir, "profile")}`, "about:blank"
], { windowsHide: true, stdio: "ignore" });
let launchError;
browser.on("error", (error) => { launchError = error; });
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const keepAlive = setInterval(() => {}, 1000);
const checks = [];
const errors = [];
let socket;

function installFixtures() {
  window.__reviewDocumentId = crypto.randomUUID();
  const nativeFetch = window.fetch.bind(window);
  const state = window.__authReview = { calls: [], access: true, challengeCount: 0, failure: document.cookie.match(/review_failure=([^;]*)/)?.[1] || "" };
  const user = { sub: "review-user", email: "review@gmail.com", name: "Review Reader", picture: "" };
  const signedIn = () => document.cookie.includes("review_session=1");
  const session = () => ({ user, csrf_token: "review-session-csrf", can_query: state.access });
  const json = (body, status = 200) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
  const clearSession = () => { document.cookie = "review_session=;Max-Age=0;path=/"; };
  const deferred = (options, name, finish) => new Promise((resolve, reject) => {
    state[`release${name}`] = () => resolve(finish());
    options.signal?.addEventListener("abort", () => {
      state[`${name.toLowerCase()}Aborted`] = true;
      reject(new DOMException("Request cancelled", "AbortError"));
    }, { once: true });
  });
  window.fetch = async (resource, options = {}) => {
    const url = new URL(typeof resource === "string" ? resource : resource.url, location.href);
    if (!url.pathname.startsWith("/api/")) return nativeFetch(resource, options);
    const headers = Object.fromEntries(new Headers(options.headers).entries());
    state.calls.push({ path: url.pathname, method: options.method || "GET", body: options.body || "", headers });
    if (state.failure === "api503") return json({ detail: "Private review diagnostic" }, 503);
    if (url.pathname === "/api/auth/me") return signedIn() ? json(session()) : json({}, 401);
    if (url.pathname === "/api/auth/config") {
      state.nonce = `review-nonce-${++state.challengeCount}`;
      state.loginCsrf = `review-login-csrf-${state.challengeCount}`;
      return json({ client_id: "review.apps.googleusercontent.com", csrf_token: state.loginCsrf, ...(state.failure === "missing-config" ? {} : { nonce: state.nonce }) });
    }
    if (url.pathname === "/api/auth/google") {
      if (state.rejectLogin) { state.rejectLogin = false; return json({}, 401); }
      if (JSON.parse(options.body).credential !== `review-token:${state.nonce}` || headers["x-csrf-token"] !== state.loginCsrf) return json({}, 403);
      const finish = () => { document.cookie = "review_session=1;path=/"; return json(session()); };
      return state.pauseLogin ? deferred(options, "Login", finish) : finish();
    }
    if (url.pathname === "/api/auth/logout") { clearSession(); return new Response(null, { status: 204 }); }
    if (url.pathname === "/api/query") {
      if (state.queryStatus === 401) { clearSession(); return json({}, 401); }
      if (!signedIn() || !state.access) return json({}, 403);
      const finish = () => json({ status: "success", sql: "SELECT 1 LIMIT 1000", message: "Private review result", tables: [], visualizations: [], kpis: [], error: null });
      return state.pauseQuery ? deferred(options, "Query", finish) : finish();
    }
    return json({}, 404);
  };
  window.google = { accounts: { id: {
    initialize(config) { state.google = config; },
    renderButton(container, options) {
      const button = document.createElement("button");
      button.textContent = "Continue with Google";
      button.style.width = `${options.width}px`;
      button.style.height = "44px";
      button.onclick = () => state.google.callback({ credential: `review-token:${state.google.nonce}` });
      container.replaceChildren(button);
    },
    disableAutoSelect() { state.autoSelectDisabled = true; },
    cancel() {}
  } } };
}

try {
  let target;
  for (let attempt = 0; attempt < 80; attempt++) {
    if (launchError) throw launchError;
    try { target = (await (await fetch(`http://127.0.0.1:${debuggingPort}/json/list`)).json()).find((item) => item.type === "page"); } catch {}
    if (target) break;
    await sleep(100);
  }
  if (!target) throw new Error("Chrome did not expose a review target");
  socket = new WebSocket(target.webSocketDebuggerUrl);
  await new Promise((resolve, reject) => { socket.onopen = resolve; socket.onerror = reject; });
  let sequence = 0;
  const pending = new Map();
  socket.onmessage = ({ data }) => {
    const message = JSON.parse(data);
    if (message.id) {
      const request = pending.get(message.id);
      pending.delete(message.id);
      if (message.error) request?.reject(new Error(message.error.message)); else request?.resolve(message.result);
    }
    if (message.method === "Runtime.exceptionThrown") errors.push(message.params.exceptionDetails);
  };
  const cdp = (method, params = {}) => new Promise((resolve, reject) => {
    const id = ++sequence;
    const timeout = setTimeout(() => { pending.delete(id); reject(new Error(`CDP timeout: ${method}`)); }, 15000);
    pending.set(id, { resolve: (value) => { clearTimeout(timeout); resolve(value); }, reject: (error) => { clearTimeout(timeout); reject(error); } });
    socket.send(JSON.stringify({ id, method, params }));
  });
  const evaluate = async (expression) => {
    const result = await cdp("Runtime.evaluate", { expression, returnByValue: true, awaitPromise: true });
    if (result.exceptionDetails) throw new Error(result.exceptionDetails.exception?.description || result.exceptionDetails.text);
    return result.result.value;
  };
  const check = (name, value) => { checks.push({ name, pass: Boolean(value) }); if (!value) throw new Error(`Failed: ${name}`); };
  const waitFor = async (expression) => {
    for (let attempt = 0; attempt < 120; attempt++) {
      if (await evaluate(`Boolean(${expression})`)) return;
      await sleep(100);
    }
    throw new Error(`Timed out: ${expression}; page: ${await evaluate("document.body.innerText.slice(0,1200)")}`);
  };
  const click = (text) => evaluate(`(() => {
    const button = [...document.querySelectorAll('button')].find((item) => item.textContent.trim() === ${JSON.stringify(text)} && item.getBoundingClientRect().width);
    if (!button || button.disabled) throw Error('Missing enabled button'); button.click();
  })()`);
  const screenshot = async (name) => {
    const result = await cdp("Page.captureScreenshot", { format: "png" });
    await writeFile(path.join(artifactDir, `${name}.png`), Buffer.from(result.data, "base64"));
  };
  const loadDocument = async (method, params = {}) => {
    const previous = await evaluate("window.__reviewDocumentId");
    await cdp(method, params);
    await waitFor(`window.__reviewDocumentId && window.__reviewDocumentId !== ${JSON.stringify(previous) || "undefined"}`);
  };
  const signedOut = async () => {
    await waitFor("document.querySelector('[data-auth-state=signedout]') && document.querySelector('.google-signin-button button')");
    check("signed out has only the dedicated sign-in page", await evaluate("location.pathname === '/signin' && !document.querySelector('textarea,.sidebar-desktop,.sidebar-trigger,.message')"));
  };
  const workspace = () => waitFor("location.pathname === '/' && document.querySelector('textarea:not(:disabled)') && document.body.innerText.includes('Review Reader')");
  const send = async (prompt) => {
    await evaluate(`(() => {
      const input = document.querySelector('textarea');
      Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value').set.call(input, ${JSON.stringify(prompt)});
      input.dispatchEvent(new Event('input', { bubbles: true }));
    })()`);
    await waitFor("!document.querySelector('.send-button').disabled");
    await evaluate("document.querySelector('textarea').form.requestSubmit()");
  };

  await cdp("Runtime.enable");
  await cdp("Page.enable");
  await cdp("Network.enable");
  await cdp("Network.setBlockedURLs", { urls: ["https://accounts.google.com/*", "https://*.googleapis.com/*"] });
  await cdp("Page.addScriptToEvaluateOnNewDocument", { source: `(${installFixtures.toString()})();` });
  await cdp("Emulation.setDeviceMetricsOverride", { width: 1440, height: 900, deviceScaleFactor: 1, mobile: false });
  await loadDocument("Page.navigate", { url: `${previewUrl}/signin` });
  await signedOut();
  check("Google receives the current server nonce", await evaluate("__authReview.google.nonce === __authReview.nonce && __authReview.google.auto_select === false"));
  check("sign-in heading has route-entry focus", await evaluate("document.activeElement === document.querySelector('#signin-heading')"));
  for (const [width, height] of [[1440, 900], [1024, 768], [390, 844], [844, 390], [320, 568]]) {
    await cdp("Emulation.setDeviceMetricsOverride", { width, height, deviceScaleFactor: 1, mobile: false });
    await sleep(250);
    const layout = await evaluate(`(() => {
      const logo = document.querySelector('.signin-page__logo').getBoundingClientRect();
      const card = document.querySelector('.signin-page__panel').getBoundingClientRect();
      const button = document.querySelector('.google-signin-button button').getBoundingClientRect();
      return { fits: document.documentElement.scrollWidth <= innerWidth && card.left >= 0 && card.right <= innerWidth && button.left >= card.left && button.right <= card.right,
        centered: Math.abs(logo.left + logo.width / 2 - document.documentElement.clientWidth / 2) < 2,
        background: Boolean(document.querySelector('.ambient-light')) && Boolean(document.querySelector('.water-sparkles')) && document.querySelectorAll('.water-sparkle').length > 0,
        oneLogo: document.querySelectorAll('.logo-frame').length === 1 && document.querySelectorAll('canvas').length <= 1 && (document.querySelectorAll('canvas').length === 1 || Boolean(document.querySelector('.logo-fallback'))) };
    })()`);
    await screenshot(`signin-${width}x${height}`);
    check(`${width}x${height}: sign-in layout fits and has one centered logo with water background (${JSON.stringify(layout)})`, layout.fits && layout.centered && layout.background && layout.oneLogo);
  }
  await cdp("Emulation.setDeviceMetricsOverride", { width: 1440, height: 900, deviceScaleFactor: 1, mobile: false });
  await evaluate("__authReview.rejectLogin = true; window.__firstNonce = __authReview.nonce");
  await click("Continue with Google");
  await waitFor("document.querySelector('.google-signin-button button') && __authReview.nonce !== window.__firstNonce");
  check("failed login refreshes the Google nonce", await evaluate("__authReview.google.nonce === __authReview.nonce"));
  await evaluate("__authReview.pauseLogin = true");
  await click("Continue with Google");
  await waitFor("document.querySelector('[data-auth-state=signingin]')");
  check("signing in cannot expose or query the workspace", await evaluate("!document.querySelector('textarea,.sidebar-trigger,.google-signin-button button') && !__authReview.calls.some((call) => call.path === '/api/query')"));
  await evaluate("__authReview.releaseLogin(); __authReview.pauseLogin = false");
  await workspace();
  check("login sends credential and login CSRF", await evaluate("__authReview.calls.some((call) => call.path === '/api/auth/google' && JSON.parse(call.body).credential.startsWith('review-token:') && call.headers['x-csrf-token'].startsWith('review-login-csrf-'))"));
  await send("How many rows?");
  await waitFor("document.body.innerText.includes('Private review result')");
  check("queries carry question and session CSRF", await evaluate("__authReview.calls.some((call) => call.path === '/api/query' && JSON.parse(call.body).question === 'How many rows?' && call.headers['x-csrf-token'] === 'review-session-csrf')"));
  await screenshot("authenticated-result");
  await loadDocument("Page.reload");
  await workspace();
  check("reload restores the session through the backend", await evaluate("__authReview.calls.some((call) => call.path === '/api/auth/me') && !__authReview.calls.some((call) => call.path === '/api/auth/google')"));
  await send("Private state before logout");
  await waitFor("document.body.innerText.includes('Private review result')");
  await evaluate("__authReview.pauseQuery = true");
  await send("Pending private query");
  await waitFor("Boolean(__authReview.releaseQuery)");
  await click("Sign out");
  await signedOut();
  check("logout aborts private queries and clears results", await evaluate("__authReview.queryAborted && !document.body.innerText.includes('Private review result') && !document.body.innerText.includes('Pending private query') && __authReview.autoSelectDisabled"));
  await evaluate("__authReview.releaseQuery(); __authReview.pauseQuery = false; __authReview.access = false");
  await click("Continue with Google");
  await waitFor("document.querySelector('[data-auth-state=pending-access]')");
  check("unapproved accounts stay on sign-in with account actions", await evaluate("location.pathname === '/signin' && document.body.innerText.includes('review@gmail.com') && !document.querySelector('textarea,.sidebar-trigger') && Boolean(document.querySelector('[data-testid=signout-button]'))"));
  await screenshot("pending-access");
  await click("Sign out");
  await signedOut();
  check("unapproved accounts can sign out from their dedicated page", await evaluate("!document.body.innerText.includes('review@gmail.com')"));
  await click("Continue with Google");
  await waitFor("document.querySelector('[data-auth-state=pending-access]')");
  await evaluate("__authReview.access = true");
  await click("Check access again");
  await workspace();
  await send("Private state before expiry");
  await waitFor("document.body.innerText.includes('Private review result')");
  await evaluate("__authReview.queryStatus = 401");
  await send("Expired session query");
  await signedOut();
  check("query 401 removes all private workspace state", await evaluate("!document.body.innerText.includes('Private review result') && !document.body.innerText.includes('Expired session query')"));
  for (const failure of ["missing-config", "api503"]) {
    await evaluate(`document.cookie = 'review_failure=${failure};path=/'`);
    await loadDocument("Page.reload");
    await waitFor("document.querySelector('[data-auth-state=unavailable]') && document.querySelector('.auth-retry')");
    check(`${failure}: retry page contains no workspace`, await evaluate("location.pathname === '/signin' && !document.querySelector('textarea,.sidebar-trigger')"));
    await screenshot(failure);
    await evaluate("__authReview.failure = ''; document.cookie = 'review_failure=;Max-Age=0;path=/'");
    await click("Try again");
    await signedOut();
  }
  check("sign-in links to both public policies", await evaluate("Boolean(document.querySelector('a[href=\"/privacy\"]')) && Boolean(document.querySelector('a[href=\"/terms\"]'))"));
  await evaluate("document.cookie = 'review_failure=api503;path=/'");
  for (const route of ["privacy", "terms"]) {
    await loadDocument("Page.navigate", { url: `${previewUrl}/${route}` });
    await waitFor("document.querySelector('[data-testid=legal-page]')");
    check(`${route}: directly accessible without auth even during an outage`, await evaluate(`location.pathname === '/${route}' && __authReview.calls.length === 0 && !document.querySelector('textarea,.google-signin-button') && document.querySelector('a[href="mailto:Spear.g.benjamin@gmail.com"]') && document.activeElement.id === 'legal-heading'`));
    await loadDocument("Page.reload");
    await waitFor("document.querySelector('[data-testid=legal-page]')");
    await cdp("Emulation.setDeviceMetricsOverride", { width: 320, height: 568, deviceScaleFactor: 1, mobile: false });
    await sleep(100);
    check(`${route}: readable on narrow mobile after reload`, await evaluate("document.documentElement.scrollWidth <= innerWidth && document.querySelector('h1').textContent === document.title.split(' | ')[0]"));
    await screenshot(`${route}-mobile`);
  }
  await evaluate("document.cookie = 'review_failure=;Max-Age=0;path=/'; document.querySelector('a[href=\"/signin\"]').click()");
  await signedOut();
  check("no uncaught browser exceptions", errors.length === 0);
  await writeFile(path.join(artifactDir, "results.json"), JSON.stringify({ checks, errors }, null, 2));
  console.log(JSON.stringify({ passed: checks.length, checks, artifactDir }, null, 2));
  try { await cdp("Browser.close"); } catch {}
} catch (error) {
  await writeFile(path.join(artifactDir, "failure.json"), JSON.stringify({ checks, errors, error: error.stack }, null, 2));
  console.error(error.stack);
  console.error(`Review artifacts: ${artifactDir}`);
  process.exitCode = 1;
} finally {
  socket?.close();
  browser.kill();
  clearInterval(keepAlive);
}
