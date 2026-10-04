// Model choices shown before /api/models answers, and in mock mode. Ids match
// the backend's provider ids, so a question sent before the list loads still
// names a model the server understands. The real list replaces this on load.
export const AI_MODELS = [
  { id: "gemini", name: "gemma-4-31b-it", description: "Google Gemini API" },
  { id: "ollama", name: "qwen3:8b", description: "Open model on the team server" },
];

export const DEFAULT_MODEL_ID = AI_MODELS[0].id;
