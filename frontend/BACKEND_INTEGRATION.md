# AQUA frontend integration

The default UI uses Google sign-in and the real same-origin Python API. It restores an Aqua session on reload, requires query access, and sends questions to `/api/query`. The existing visual demo is available only with the public build flag `VITE_AQUA_DEMO_MODE=true`; it is visibly labeled **Demo · fictional sample data** and makes no API or Google requests.

## Google sign-in and session lifecycle

`src/services/authClient.js` owns auth HTTP requests. `src/hooks/useGoogleAuth.js` owns identity, login challenge, CSRF state, and retry/logout behavior in memory. `src/services/googleIdentity.js` loads Google's supported GIS script; `SignInPanel.jsx` renders the official **Continue with Google** button. No Google client secret, credentials, session tokens, or database passwords belong in the frontend environment. The public client ID is obtained from the backend.

| Request | Frontend behavior |
|---|---|
| `GET /api/auth/me` | Restore `{user: {sub, email, name, picture}, csrf_token, can_query}`; 401 means signed out |
| `GET /api/auth/config` | Obtain `{client_id, nonce, csrf_token}` and the backend's HttpOnly challenge cookie |
| `POST /api/auth/google` | Send JSON `{credential}` and challenge `X-CSRF-Token`; GIS initializes with the supplied client ID and nonce |
| `POST /api/auth/logout` | Send session `X-CSRF-Token`; accept empty 204, disable Google automatic account selection, clear private in-memory state |

All auth/query fetches use relative URLs, `credentials: "same-origin"`, and `cache: "no-store"`. The browser supplies `Origin`. The Aqua session stays in an HttpOnly cookie; Google credentials and CSRF tokens are never written to local/session storage. Failed login starts a new challenge. Missing setup or provider/network failure shows a user-safe retry state. A signed-in account with `can_query: false` sees pending access and a disabled composer.

`App.jsx` shows a dedicated `/signin` page until a live session has query access. `src/pages/SignInPage.jsx` reuses Aqua's background, ambient light, water sparkles, and animated logo around the Google controls. The private workspace, sidebar, and composer mount only for approved users (or explicit demo mode). Pending-access accounts remain on the sign-in page with account details, access recheck, and sign-out actions.

The lightweight History API gate replaces the path with `/signin` or `/` after session/access changes and browser back navigation. It retains the auth hook across those transitions, sets a page-specific title, and focuses the destination heading. `/privacy` and `/terms` render `LegalPage.jsx` without mounting the auth hook, so both documents remain available before login and during auth outages. Sign-in links to both; the documents link to each other and back to sign-in. Direct visits to all three public paths require the hosting server to serve the frontend's `index.html`; `/api/*` must continue routing to Python rather than the frontend fallback. The owner should review the policy text against actual deployment and provider practices before publishing.

`App.jsx` keys the private workspace by the authenticated Google `sub`. Logout, account change, session expiry, and access rechecks unmount that workspace, abort pending requests, and discard drafts, messages, and private results. A failed server logout shows an error and offers another attempt; private chat state has already been cleared. Query 401/403 responses refresh auth/access without automatically resending the question. Backend setup and the Cloudflare `/api` routing requirements are in `../docs/google-signin.md`.

## Client boundary

`src/services/aquaClient.js` is the only module components call. It hands requests to `apiClient.js` (the real transport) or `mockClient.js` (the mock). The UI calls:

```js
sendMessage({ prompt, csrfToken, demoMode, conversationId, requestId, modelId, signal, onFirstContent, onContent })
retryMessage({ prompt, csrfToken, demoMode, conversationId, requestId, modelId, signal, onFirstContent, onContent })
```

Both return a promise resolving to the normalized response object below. Live requests require a session `csrfToken` and map `prompt` to backend `question`. Demo requests preserve optional cumulative-text callbacks `(fragment, { conversationId, requestId, modelId })`; `modelId` is omitted when not supplied. Live requests return the complete result without simulated streaming. Presentation components do not make API requests.

The Vite `/api` proxy is unchanged for development. Production must route the website's `/api/*` to the Python backend on the same public origin; cross-origin auth and an alternate API-base URL are not configured. `VITE_AQUA_DEMO_MODE` is the only new public frontend setting, and defaults to live mode when unset. It must be `true` explicitly to run the offline visual demo.
The real backend does not stream: the callbacks are not called, and the promise resolves with the complete answer, which can take 20 to 80 seconds. A retry sends the same question again.

## Request

The UI's `prompt` becomes the backend's `question`, and the selected model id becomes `model`:

```json
{ "question": "What are the top 3 film categories by total payment revenue?", "model": "gemini" }
```

Every response also carries `sql`, the query that produced the answer (or that was refused). The UI shows it under the answer.

## Success response

```json
{
  "status": "success",
  "sql": "...",
  "message": "Payroll was your largest expense category.",
  "tables": [
    {
      "id": "expenses-by-category",
      "title": "Expenses by Category",
      "columns": [
        { "key": "category", "label": "Category", "type": "string" },
        { "key": "amount", "label": "Amount", "type": "currency" },
        { "key": "share", "label": "% of Total", "type": "percentage" }
      ],
      "rows": [
        { "category": "Payroll", "amount": 184200, "share": 48.2 }
      ]
    }
  ],
  "visualizations": [
    {
      "id": "expenses-chart",
      "type": "bar",
      "title": "Expenses by Category",
      "tableId": "expenses-by-category",
      "xKey": "category",
      "yKey": "amount"
    }
  ],
  "kpis": [
    {
      "id": "monthly-expenses",
      "label": "Monthly expenses",
      "value": 382150,
      "type": "currency",
      "change": 2.9,
      "direction": "up"
    }
  ]
}
```

`message` is Markdown text, rendered without raw HTML. `tables` and `visualizations` are separate structured data; the UI never derives financial data from prose. Column types currently supported are `string`, `currency`, `percentage`, `number`, and `date`. Rows are objects keyed by each column's `key`.

Visualization types are allowlisted: `bar`, `line`, `area`, and `kpi`. Chart descriptors reference a table by `tableId` and its `xKey`/`yKey`; KPI descriptors reference the top-level `kpis` array. Unsupported or invalid descriptors are not rendered.

## Errors and no data

`apiClient.js` turns transport problems into the same error shape: HTTP 429 (more than 10 questions a minute) becomes a retryable `rate_limited` error, 422 becomes a non-retryable `invalid_question` error, and a network failure or a non-JSON proxy page becomes a retryable `unavailable` error. Refused SQL (`rejected`, `query_failed`) keeps the backend's reason after a plain-language sentence, and keeps `sql` so the UI can show what was not run.

Return normalized, user-safe errors:

```json
{
  "status": "error",
  "error": {
    "code": "unavailable",
    "message": "AQUA couldn't complete that request. Please try again.",
    "retryable": true
  }
}
```

The client discards raw HTTP error details and returns safe 401/403/422/service messages. A rejected SQL result keeps its SQL but uses a safe rephrasing message; a live service failure is retryable, while auth/access failures are not. SQL appears in an escaped **View SQL** disclosure. A no-data result is a normal success with an explanatory `message` and empty `tables`, `visualizations`, and `kpis`.

## Simulated streaming and request routing

In explicit demo mode, the mock client waits approximately 1050 ms, then emits up to six cumulative text fragments at 85 ms intervals. The first invokes `onFirstContent`; subsequent fragments invoke `onContent`. Fragments have `status: "streaming"`, cumulative Markdown `message`, and empty `tables`, `visualizations`, and `kpis`. The Promise resolves the complete normalized response, including structured content. Demo mode makes no network requests. Live mode submits one authenticated POST and uses the same complete-response lifecycle.

`useChat.js` captures the conversation ID, request ID, selected model ID, user message ID, and reply ID before starting the request. It patches the same AQUA message during streaming and completion. `waiting` stops at first content; `pending` lasts through completion and prevents another request in that conversation. Switching chats clears decorative effects while the original request finishes in its original record. Separate conversations can process independently. Updates must match both conversation and current request ID; stale responses must never patch another chat. Changing the selected model applies to subsequent prompts; it does not rewrite an active request. Retry retains the failed reply's model ID when available.

Normalized errors finish the request, retain the prompt, remove waiting effects, and expose retry only when `retryable` is true. Retry uses a fresh request ID and replaces the existing reply without appending a second user message. Unmount aborts all outstanding controllers. An `AbortError` is cancellation, not a user-facing server error. When wiring a real stream, retain these lifecycle rules and validate complete structured descriptors at the client boundary.

While a question is pending, the send arrow becomes an enabled square **Stop response** button. It aborts the active conversation's browser request, clears waiting effects, preserves any partial text and the next draft, and marks the reply stopped. Request IDs and abort checks discard late responses without affecting a newer question or another conversation. Enter in the textarea never triggers stop; keyboard users can activate the stop button itself. The synchronous backend has no cancellation endpoint, so already-running model/database work may finish even after the browser stops waiting. The main workspace logo has no visible tagline; a hidden heading retains screen-reader navigation and route-entry focus.

The JSON request example above is the backend request. Conversation/request IDs and demo model IDs remain frontend routing metadata and are not sent to Python. Only `question` is sent in a live query body.

## Projects, conversations, and drafts

In demo mode, `src/mocks/navigation.js` supplies stable project/folder IDs, nested `children`, `conversationIds` references, FAQ prompts, and distinct fictional seed conversations. Live mode starts with a single empty conversation and no sample projects/history. `src/hooks/useChat.js` owns conversation records, active ID, expanded folder IDs, drafts, and request state. Both Projects and Recent Chats select the same records. A new chat joins Recent Chats once it contains a message; Ask a Question retains prior chats within that authenticated session and focuses the composer. FAQ selection fills the composer without submitting. Live questions are limited to 2,000 characters. Chat history remains in memory and is lost on reload or account/session changes; there is no new persistence, customer database onboarding, or upload feature.

## AI model selection

The sidebar header uses a keyboard-accessible menu for model selection. On load, `useChat.js` asks `GET /api/models` for the models the server can run (server default first) and selects the default unless the current choice is on the list. Until that answers, or if it fails, `src/mocks/aiModels.js` supplies the same ids (`gemini`, `ollama`). The selected id is kept in session memory so desktop and mobile navigation share it, recorded on each request and message, and sent as `model`. Mock replies remain scenario-based and do not run either model.

## Financial values and exports

Percentages are **percentage points**: `48.2` displays as `48.2%`, not `4820%`. Currency columns accept optional ISO `currency` and `fractionDigits`; `table.currency` is a fallback and USD/zero fractional digits are defaults. Number columns use at most two fractional digits. Date strings should be valid ISO dates (`YYYY-MM-DD`); display uses local noon to avoid shifting a date across time zones. Null values display as an em dash and export as empty cells.

Sortable headers are semantic buttons with `aria-sort` on the column header. Numeric values sort numerically; nulls sort last in both directions. Tables retain their own keyboard-accessible horizontal scroll region on narrow screens. CSV exports the current sorted rows with a UTF-8 BOM, CRLF records, escaped quotes/delimiters/newlines, and raw numeric values. Spreadsheet-sensitive strings beginning with `=`, `+`, `-`, or `@` after whitespace are prefixed with an apostrophe, including text in a numeric-typed column; actual negative numbers are preserved. CSV is Tableau-friendly output, not Tableau integration. Clipboard and export failures produce visible status text, and temporary download URLs are released.

## Supplied models and visual fallbacks

The supplied GLBs remain unchanged. The logo loads `AQUA_V2_Final.glb`, selects `AQUA_V2_STUDIO`, and plays `AQUA_Idle` (8.033 seconds) through capped 30 fps demand rendering, pausing when the document is hidden or reduced motion applies. The composer selects only `AQUA_CHAT_BAR_V6_CLEAR_GLASS`. Runtime-hidden nodes are `AQUA_Placeholder_FRONT`, `AQUA_Cursor`, `AQUA_Send_Arrow_Shaft`, `AQUA_Send_Arrow_Head`, and `AQUA_Backdrop`; the original glass body and glass button remain the visible shell.

The browser derives volume thickness and inset transmission receivers from the supplied geometry because the GLB exports transmission/IOR without a volume thickness extension. The receivers share softly lit, partially transparent blue-gray/aqua illumination across the body and button; controlled white and aqua studio reflections add edge depth while the original glass tint, transmission, roughness, and IOR remain intact. The closed glass meshes render outward faces; a body-only shader suppresses lower-bevel specular bands while retaining the upper reflection. Browser glass cannot reproduce Blender path tracing or refract underlying HTML. Orthographic projection measures the usable input/button regions and real upper surface for the decorative SVG message neck and thinking-bubble emitters. Real textarea/button/message/table semantics remain in HTML.

The main logo and composer use two bounded canvases with capped DPR, no post-processing, and no per-message/bubble WebGL. The sidebar contains the AI model selector. The composer and logo renderers load lazily. Genuine loading/WebGL failures keep functional HTML controls. `AQUA_V2_Final_static.svg` is a static projection of the supplied logo triangles used only during loading or rendering failure, reproducible with `node frontend/scripts/create-logo-fallback.mjs`. A reactive media-query hook disables float, physical formation, bubble travel/pop, and decorative glass transitions when reduced motion is enabled, including changes during an open session.

Above 900px, the composer keeps its 640px width and uses slightly taller vertical camera framing for approximately 73px visible glass height. The cloned glass button and HTML controls align to the projected shell's vertical center. Desktop text is 14px and the send arrow is 18px; measured text padding centers short and wrapped drafts while retaining scrolling and a minimum 44px button target. Mobile framing and sizing remain unchanged. `node frontend/checks/browser-review.mjs --desktop-composer` reviews three desktop sizes, centering, multiline input, waiting-bubble coverage, Enter submission, and unchanged mobile sizing.

`WaterSparkles.jsx` adds a bounded field of aqua droplets and specular glints behind the content using CSS transforms and opacity, without another canvas or dependency. Fewer glints appear on mobile; animations pause while the document is hidden and become still under reduced motion. The layer ignores pointer input and is hidden from assistive technology.

## Local verification

For the live-mode sign-in flow, start the frontend with demo mode unset, then run `node frontend/checks/auth-page-review.mjs`. This uses installed Chrome with a temporary isolated profile and mocked API/Google responses. It checks responsive layouts, challenges, CSRF transport, session restoration, access denial, logout and query cancellation, expiry, outage recovery, and public policy routes. It writes results and screenshots to a new temporary `aqua-auth-page-review-*` directory. Set `AQUA_REVIEW_URL` or `AQUA_CHROME_EXECUTABLE` if the local preview URL or browser location differs. This review does not establish a real Google login or deployed Cloudflare configuration.

Three.js and the roughly 6.3 MB of active GLBs remain the principal download/rendering costs. The static fallback logo is approximately 2.1 MB uncompressed (336 KB gzip). Software-only WebGL can stutter; browser screenshots and functional checks do not establish frame-rate guarantees or final human visual approval.

`npm test` runs every `checks/*.test.mjs` suite, including the real client's tests against a stand-in `fetch`. `browser-review.mjs` exercises scripted mock scenarios, so run the preview with `VITE_AQUA_DEMO_MODE=true` for it.

## Production

The frontend image builds the site (`npm ci`, `vite build`) and serves `dist/` with nginx on port 5173 (`nginx.conf`). nginx forwards `/api` to the backend on 127.0.0.1:8000, waits up to 300 seconds for an answer, limits each visitor to 10 questions a minute, and caches hashed assets for a year while never caching `index.html`. `npm run dev` is for local work only.

## Frontend touch points

Auth transport lives in `authClient.js`, Google Identity Services loading in `googleIdentity.js`, and session lifecycle in `useGoogleAuth.js`. Query transport lives in `apiClient.js` (it adds the session's `X-CSRF-Token` and maps 401 and 403 to `sign_in_required` and `access_denied`, which `useChat.js` answers by refreshing the session). API changes belong in `src/services/apiClient.js` and, if the contract changes, this document and `CLAUDE.md`. The chat, logo, message presentation, table, chart, and styling components should not need API-specific redesign or direct fetch calls.
