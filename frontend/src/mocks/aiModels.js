// Temporary choices for the selector. Replace this catalog with the available
// models when model discovery is connected to the API client.
export const AI_MODELS = [
  { id: "qwen3:8b", name: "Qwen3 8B", description: "Standard model" },
  { id: "qwen3:4b", name: "Qwen3 4B", description: "Compact model" },
];

export const DEFAULT_MODEL_ID = AI_MODELS[0].id;
