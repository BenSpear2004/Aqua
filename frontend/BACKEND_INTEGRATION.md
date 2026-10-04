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

## Replacement point

`src/services/aquaClient.js` owns the live query transport and explicit demo transport. The UI calls:

```js
sendMessage({ prompt, csrfToken, demoMode, conversationId, requestId, modelId, signal, onFirstContent, onContent })
retryMessage({ prompt, csrfToken, demoMode, conversationId, requestId, modelId, signal, onFirstContent, onContent })
```

Both return a promise resolving to the normalized response object below. Live requests require a session `csrfToken` and map `prompt` to backend `question`. Demo requests preserve optional cumulative-text callbacks `(fragment, { conversationId, requestId, modelId })`; `modelId` is omitted when not supplied. Live requests return the complete result without simulated streaming. Presentation components do not make API requests.

The Vite `/api` proxy is unchanged for development. Production must route the website's `/api/*` to the Python backend on the same public origin; cross-origin auth and an alternate API-base URL are not configured. `VITE_AQUA_DEMO_MODE` is the only new public frontend setting, and defaults to live mode when unset. It must be `true` explicitly to run the offline visual demo.

## Request

```json
{ "question": "What was our largest expense category?" }
```

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

The JSON request example above is the backend request. Conversation/request IDs and demo model IDs remain frontend routing metadata and are not sent to Python. Only `question` is sent in a live query body.

## Projects, conversations, and drafts

In demo mode, `src/mocks/navigation.js` supplies stable project/folder IDs, nested `children`, `conversationIds` references, FAQ prompts, and distinct fictional seed conversations. Live mode starts with a single empty conversation and no sample projects/history. `src/hooks/useChat.js` owns conversation records, active ID, expanded folder IDs, drafts, and request state. Both Projects and Recent Chats select the same records. A new chat joins Recent Chats once it contains a message; Ask a Question retains prior chats within that authenticated session and focuses the composer. FAQ selection fills the composer without submitting. Live questions are limited to 2,000 characters. Chat history remains in memory and is lost on reload or account/session changes; there is no new persistence, customer database onboarding, or upload feature.

## AI model selection

The demo sidebar retains the keyboard-accessible model menu and fictional selection behavior. `src/mocks/aiModels.js` supplies `Qwen3 8B` / `Qwen3 4B`; selection remains in memory, and request metadata preserves it across navigation/retries. Mock replies do not run either model. Live mode displays **AQUA** without a model menu because the Python backend chooses its model from server configuration.

Selectable model routing would require a separate backend contract; do not send the demo `modelId` to `/api/query` or imply it selects the production model.

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

Run `npm --prefix frontend run build` and `node --test frontend/checks/*.test.mjs`. The transport checks mock fetch and never contact Google or a real database. Start a preview with `VITE_AQUA_DEMO_MODE=true` for the original visual check script: `node frontend/checks/browser-review.mjs` uses installed Windows Chrome and Node's native DevTools connection on `http://127.0.0.1:5173`; it adds no dependency. It reviews 1440×900, 1024×768, and 390×844, writes screenshots and sampled birth/pop timelines to the temporary `aqua-frontend-review` directory, and exercises demo navigation, structured results, exports, keyboard behavior, motion preferences, interruptions, and context-loss fallbacks. Optional `--missing-models` and `--no-webgl` modes deliberately inject asset/graphics failures; expected handled diagnostics in those modes do not imply normal-session runtime errors.

Three.js and the roughly 6.3 MB of active GLBs remain the principal download/rendering costs. The static fallback logo is approximately 2.1 MB uncompressed (336 KB gzip). Software-only WebGL can stutter; browser screenshots and functional checks do not establish frame-rate guarantees or final human visual approval. This frontend change preserves Docker and Vite configuration; actual auth environment values, Google registration, and Cloudflare routing must be configured separately.

## Frontend touch points

Auth transport lives in `authClient.js`, GIS loading in `googleIdentity.js`, and session lifecycle in `useGoogleAuth.js`. Query transport and normalization stay in `aquaClient.js`, with `useChat.js` preserving request IDs and cancellation. The chat, logo, table, and chart components remain presentation boundaries. Auth UI uses `components/auth/` and `styles/auth.css`; no package dependencies or Vite/deployment configuration changed.
