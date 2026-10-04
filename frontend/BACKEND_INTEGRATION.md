# AQUA frontend integration

The UI currently runs entirely on local mock responses. It makes no backend requests.

## Replacement point

Replace the mock internals in `src/services/aquaClient.js`. The UI calls:

```js
sendMessage({ prompt, conversationId, requestId, modelId, signal, onFirstContent, onContent })
retryMessage({ prompt, conversationId, requestId, modelId, signal, onFirstContent, onContent })
```

Both return a promise resolving to the response object below. Only `prompt` is required; the original Promise-only call remains supported. Optional cumulative-text callbacks receive `(fragment, { conversationId, requestId, modelId })`; `modelId` is omitted when not supplied. Keep transport, endpoint selection, cancellation, and error normalization inside this client; presentation components should not need API-specific changes.

For a future deployment, centralize the API origin in `VITE_AQUA_API_BASE_URL`. When unset, the existing Vite `/api` proxy can be used in development. This variable is configuration, not a place for secrets. Never put provider credentials in frontend code.

## Request

```json
{ "prompt": "What was our largest expense category?" }
```

## Success response

```json
{
  "status": "success",
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

Do not return stack traces or internal network/provider details for display. A no-data result is a normal success with an explanatory `message` and empty `tables`, `visualizations`, and `kpis`.

## Simulated streaming and request routing

The mock client waits approximately 1050 ms, then emits up to six cumulative text fragments at 85 ms intervals. The first invokes `onFirstContent`; subsequent fragments invoke `onContent`. Fragments have `status: "streaming"`, cumulative Markdown `message`, and empty `tables`, `visualizations`, and `kpis`. The Promise resolves the complete normalized response, including structured content. No network requests are made.

`useChat.js` captures the conversation ID, request ID, selected model ID, user message ID, and reply ID before starting the request. It patches the same AQUA message during streaming and completion. `waiting` stops at first content; `pending` lasts through completion and prevents another request in that conversation. Switching chats clears decorative effects while the original request finishes in its original record. Separate conversations can process independently. Updates must match both conversation and current request ID; stale responses must never patch another chat. Changing the selected model applies to subsequent prompts; it does not rewrite an active request. Retry retains the failed reply's model ID when available.

Normalized errors finish the request, retain the prompt, remove waiting effects, and expose retry only when `retryable` is true. Retry uses a fresh request ID and replaces the existing reply without appending a second user message. Unmount aborts all outstanding controllers. An `AbortError` is cancellation, not a user-facing server error. When wiring a real stream, retain these lifecycle rules and validate complete structured descriptors at the client boundary.

The JSON request example above is the minimal public request. Conversation/request IDs are frontend routing metadata and can be included in the future transport contract once agreed with the backend team. The UI makes no assumption about an existing server endpoint or its response schema; adapt any mismatch inside `aquaClient.js`.

## Projects, conversations, and drafts

`src/mocks/navigation.js` supplies stable project/folder IDs, nested `children`, `conversationIds` references, FAQ prompts, and distinct fictional seed conversations. `src/hooks/useChat.js` owns the conversation records, active ID, expanded folder IDs, per-conversation draft, and request state. Both Projects and Recent Chats select the same records. A new chat joins Recent Chats once it contains a message; Ask a Question retains previous records and focuses the composer. FAQ selection fills the current draft without submitting it. Everything is in memory and is lost on reload; there is no backend persistence, bank access, upload, or authentication.

## AI model selection

The sidebar header uses a keyboard-accessible menu for model selection. `src/mocks/aiModels.js` holds the temporary names and stable IDs (`Qwen3 8B` / `Qwen3 4B`), which will be populated later. `useChat.js` owns the selected ID in session memory so desktop and mobile navigation share it, including after starting or switching conversations. Each new request records its model ID on the request and messages and passes it to `aquaClient.js`. Mock replies remain scenario-based and do not run either model.

When model discovery is connected, replace the temporary catalog through the client boundary and validate the selected ID against the server's available models. The current Python query endpoint accepts `question` and chooses its model from server configuration; selectable backend routing is not implemented by this frontend change. Map frontend `prompt` to the agreed request shape and coordinate model routing before sending `modelId` to a real endpoint.

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

Run `npm --prefix frontend run build` and `node --test frontend/checks/*.test.mjs`. With the existing local preview on `http://127.0.0.1:5173`, `node frontend/checks/browser-review.mjs` uses installed Windows Chrome and Node's native DevTools connection; it adds no dependency. It reviews 1440×900, 1024×768, and 390×844, writes screenshots and sampled birth/pop timelines to the temporary `aqua-frontend-review` directory, and exercises navigation, structured results, exports, keyboard behavior, motion preferences, interruptions, and context-loss fallbacks. Optional `--missing-models` and `--no-webgl` modes deliberately inject asset/graphics failures; expected handled diagnostics in those modes do not imply normal-session runtime errors.

Three.js and the roughly 6.3 MB of active GLBs remain the principal download/rendering costs. The static fallback logo is approximately 2.1 MB uncompressed (336 KB gzip). Software-only WebGL can stutter; browser screenshots and functional checks do not establish frame-rate guarantees or final human visual approval. No Docker, Vite proxy, backend, server, or deployment changes are needed for this handoff.

## Frontend touch points

Backend integration should primarily change `src/services/aquaClient.js` and, if the contract changes, this document and response validation near that boundary. `src/hooks/useChat.js` may need a small update for streaming lifecycle. The chat, logo, message presentation, table, chart, and styling components should not need API-specific redesign or direct fetch calls.
