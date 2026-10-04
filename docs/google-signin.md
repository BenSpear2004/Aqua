# Google sign-in for Aqua

The frontend uses Google's supported sign-in button, restores Aqua sessions on reload, and sends approved users' questions to the backend. The backend verifies the Google Identity Services (GIS) ID token and creates an Aqua session in a signed cookie. It does not store accounts or sessions in a database.

## Server configuration

Set these values in the server's private environment using `.env.example` as the reference:

Keep the actual `/srv/bank-ai/.env` on the server. Commit and pull application code and the blank `.env.example` template only; do not copy the template over an existing server `.env`.

| Variable | Value |
|---|---|
| `GOOGLE_CLIENT_ID` | The Google OAuth **Web application** client ID |
| `SESSION_SECRET` | A randomly generated secret of at least 32 characters, shared by all backend instances |
| `APP_ORIGIN` | `https://aqua-ai.us`, or the exact origin users actually visit |
| `SESSION_MAX_AGE_SECONDS` | Default `3600`; allowed range `300` to `86400` |
| `AUTH_ALLOWED_EMAILS` | Comma-separated approved emails; verified Gmail or Google Workspace accounts only |
| `AUTH_ALLOWED_GOOGLE_SUBS` | Comma-separated approved Google account `sub` identifiers |

Generate a secret locally with `python -c "import secrets; print(secrets.token_urlsafe(48))"`, then store it privately on the server. It must never appear in frontend variables, source control, or chat. The client ID is public; it is not the session secret. Blank allowlists let people sign in but deny all queries. A Google account using a third-party email address without a verified Google Workspace identity must be approved by `sub`, not email.

Missing Google client ID or session secret makes auth and queries return 503; `/api/health` remains available. `DATABASE_URL` still supplies the existing read-only database connection. Approval grants access to that single configured database; it does not select or onboard a customer's database.

For development, set `APP_ORIGIN=http://localhost:5173` and use that exact address in the browser. HTTP is accepted only for loopback origins. Production sessions use `Secure`, `HttpOnly`, `SameSite=Lax`, host-only cookies with an expiry; local HTTP omits `Secure`. Cookies are signed, not encrypted. No database credentials or Google ID tokens are stored in them.

## Google Cloud setup

Select the OAuth **Web application** client. Add `https://aqua-ai.us` to **Authorized JavaScript origins**. If using localhost, add `http://localhost` and `http://localhost:5173`. Configure Aqua branding, support email, homepage, privacy policy, and authorized domain. Sign-in uses basic identity information; no Google data API permissions are needed. This JavaScript callback flow needs neither an authorized redirect URI nor a Google client secret. See [Google's setup guide](https://developers.google.com/identity/gsi/web/guides/get-google-api-clientid).

Use one canonical production origin. If `www.aqua-ai.us` redirects to `aqua-ai.us`, the login page and API should both use the latter. The backend accepts only the configured `APP_ORIGIN`; adding another Google JavaScript origin does not change Aqua's origin checks.

The frontend now includes public policy pages, linked from sign-in. After deploying and reviewing the text, enter `https://aqua-ai.us/privacy` and `https://aqua-ai.us/terms` in Google Auth Platform branding. They use AQUA as the service name and Benjamin / `Spear.g.benjamin@gmail.com` as the owner-supplied contact. These are starting documents based on the current code, not a legal compliance certification. Before publishing, confirm the privacy text matches the actual model server, Cloudflare and provider settings, and any operational retention practices. Update the documents when those practices change.

## Frontend integration

The integration lives in `frontend/src/hooks/useGoogleAuth.js`, `frontend/src/services/authClient.js`, and `frontend/src/services/googleIdentity.js`. `frontend/src/pages/SignInPage.jsx` provides the dedicated `/signin` page with Aqua's existing background, sparkles, centered logo, and official Google button. Approved users enter the workspace at `/`; unapproved users stay on the sign-in page with account details and sign-out/access-check actions. Session loss or logout returns to `/signin` and clears private workspace state. Live API requests are the default; `VITE_AQUA_DEMO_MODE=true` explicitly enables fictional sample data and bypasses live auth and queries for local demonstrations. Do not enable demo mode for the production build.

Use relative `/api/...` URLs on the same origin. Set `credentials: "same-origin"` and `cache: "no-store"` for auth requests. Keep tokens in memory, not local storage.

1. Fetch `GET /api/auth/config`. It returns `{client_id, nonce, csrf_token}` and sets a signed HttpOnly login challenge cookie valid for ten minutes.
2. Load Google's supported script, `https://accounts.google.com/gsi/client`. Initialize `google.accounts.id` with the returned `client_id`, returned `nonce`, and a JavaScript `callback`; render the Google sign-in button. Do not use GIS's redirect/form-post mode for this endpoint. See [Google's JavaScript reference](https://developers.google.com/identity/gsi/web/reference/js-reference).
3. In the callback, send the returned `credential` to `POST /api/auth/google`. Use `Content-Type: application/json`, `X-CSRF-Token` from config, and body `{"credential": credential}`. The browser supplies `Origin`; JavaScript should not try to set it. The backend checks the challenge, CSRF token, origin, Google signature, audience, issuer, expiry, and nonce before creating the session.
4. Store `{user: {sub, email, name, picture}, csrf_token, can_query}` from the successful response in memory. The session cookie stays HttpOnly. `can_query: false` means the user has signed in but has not been approved to access the configured database.
5. On reload, fetch `GET /api/auth/me`. A valid session returns the same identity/access/CSRF fields; 401 means show sign-in again. Fetch a new config challenge before a new login attempt.
6. For `POST /api/query`, send the session `X-CSRF-Token` and JSON `{"question": prompt}`. `frontend/src/services/aquaClient.js` maps the composer's prompt to this API field. Session, origin, CSRF, and account approval are checked before database/model work.
7. For logout, send `POST /api/auth/logout` with the session `X-CSRF-Token`. On 204, clear frontend user state and any private in-memory results. Google `disableAutoSelect()` can prevent immediately signing the same user back in. Logout does not revoke the user's Google account permissions.

Handle 401 for invalid login credentials or sessions by returning to sign-in, 403 by showing access or CSRF failure, and 503 by showing a configuration or Google verification availability error. Avoid retrying a query automatically after a session failure. Auth responses use `Cache-Control: no-store`.

Google `sub` is the stable account identifier. Email-based approval follows Google's distinction between Gmail/Workspace and third-party email accounts; see [Google's token verification guide](https://developers.google.com/identity/gsi/web/guides/verify-google-id-token). Token verification uses Google's public signing keys, so the backend needs outbound HTTPS access to fetch them.

## Cloudflare and deployment

The repository describes an Ubuntu Docker backend on port 8000 and a Vite proxy on port 5173. The user confirmed Cloudflare Tunnel hosting; tunnel routing configuration is managed separately and is not present in this checkout.

The site uses a Cloudflare Tunnel to the server. Route the public origin's `/api/*` requests to this Python backend, including auth and query routes. Preserve cookies, `Set-Cookie`, `Origin`, and `X-CSRF-Token`; bypass caching for `/api/*`. Keep public HTTPS enabled and trust forwarded headers only from the known reverse proxy. Use `APP_ORIGIN` as the canonical public browser origin regardless of internal HTTP transport. Serve the frontend's `index.html` for direct `/signin`, `/privacy`, and `/terms` visits. A production static frontend must have an equivalent `/api` route; Vite's development proxy is not part of a static build. All backend instances need the same session secret and access configuration.

If the frontend has a Content Security Policy or popup restrictions, apply [Google's GIS setup requirements](https://developers.google.com/identity/gsi/web/guides/get-google-api-clientid). The frontend container currently starts Vite's dev server; the project guide calls for a production build before public deployment.

Verify a real login, reload, approved query, denied query, and logout through the final HTTPS origin after deployment configuration. Automated tests mock Google verification and the model; they do not prove the Google client registration or Cloudflare routing works.

### Deployment checks

After a human commits these changes and merges them into the server's branch, run on Ubuntu:

```bash
cd /srv/bank-ai
git pull --ff-only
test -f backend/auth/router.py
docker compose up -d --build --force-recreate backend frontend
curl -s -o /dev/null -w '%{http_code}\n' https://aqua-ai.us/api/auth/config
curl -s -o /dev/null -w '%{http_code}\n' https://aqua-ai.us/api/auth/me
```

With the private environment configured, expect `200` for config and `401` for an unauthenticated session check. `404` means the new backend route has not reached the public site; `503` means missing auth settings or an unavailable service. A healthy `/api/health` alone does not establish auth readiness. Confirm the running deployment's frontend image/proxy before rebuilding: the reported server uses Nginx, while this checkout's frontend Dockerfile still starts Vite. Preserve the production static-serving setup and `/api` proxy when reconciling branches.

## Session limits

Sessions have a fixed expiry after the configured lifetime; reading the session or sending queries does not extend it. Logout clears this browser's cookie; a copied cookie remains valid until expiry. Rotating `SESSION_SECRET` invalidates all existing sessions. Access approval is checked against current server configuration on each query; updating environment allowlists requires restarting the affected instances. Signed cookies do not provide durable per-session revocation or multi-customer database isolation.
